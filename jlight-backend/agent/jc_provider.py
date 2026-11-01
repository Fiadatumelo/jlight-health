"""Optional, privacy-bounded language explanation for deterministic JLIGHT evidence.

The deterministic intelligence engine remains authoritative for findings and status.
This adapter may explain an already-minimised summary; it cannot create findings,
change severity, clear review requirements, or perform workspace actions.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class JCProviderUnavailable(RuntimeError):
    """Provider is not configured or cannot be reached."""


class JCProviderInvalidResponse(RuntimeError):
    """Provider output did not satisfy the bounded explanation contract."""


_ALLOWED_INTENTS = {"explain_findings", "summarise", "next_steps"}
_FORBIDDEN_KEYS = {
    "patient_id", "patientid", "participant_id", "participantid", "mrn",
    "name", "email", "phone", "date_of_birth", "dob", "sequence",
    "fastq", "fasta", "raw_reads", "clinical_narrative",
}
_ID_LIKE = re.compile(r"(?i)(?:\b\d{13}\b|\b[A-Z]{2,5}\d{5,}\b|[\w.+-]+@[\w.-]+\.[A-Z]{2,})")


def _assert_minimised(value: Any, path: str = "summary") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _FORBIDDEN_KEYS:
                raise ValueError(f"Sensitive field is not permitted at {path}.{normalized}")
            _assert_minimised(child, f"{path}.{normalized}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value[:100]):
            _assert_minimised(child, f"{path}[{index}]")
    elif isinstance(value, str):
        if len(value) > 1000 or _ID_LIKE.search(value):
            raise ValueError(f"Potential identifier or unbounded text is not permitted at {path}")
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise ValueError(f"Unsupported evidence value at {path}")


def explain_jlight_evidence(summary: Mapping[str, Any], intent: str = "explain_findings") -> dict[str, Any]:
    """Return a bounded, non-authoritative explanation of deterministic evidence."""
    if intent not in _ALLOWED_INTENTS:
        raise ValueError("Unsupported JC explanation intent")
    if not isinstance(summary, Mapping) or not summary:
        raise ValueError("A non-empty deterministic evidence summary is required")
    _assert_minimised(summary)

    api_key = os.environ.get("JLIGHT_JC_PROVIDER_API_KEY", "").strip()
    if not api_key:
        raise JCProviderUnavailable("JC language provider is not configured")
    endpoint = os.environ.get(
        "JLIGHT_JC_PROVIDER_URL", "https://api.openai.com/v1/chat/completions"
    ).strip()
    if not endpoint.startswith("https://"):
        raise JCProviderUnavailable("JC provider endpoint must use HTTPS")
    model = os.environ.get("JLIGHT_JC_PROVIDER_MODEL", "gpt-4.1-mini").strip()
    if not model or len(model) > 100:
        raise JCProviderUnavailable("JC provider model configuration is invalid")

    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "key_observations": {"type": "array", "items": {"type": "string"}},
            "uncertainties": {"type": "array", "items": {"type": "string"}},
            "human_review_required": {"type": "boolean"},
            "limitations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "key_observations", "uncertainties", "human_review_required", "limitations"],
    }
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "jlight_evidence_explanation", "strict": True, "schema": schema},
        },
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are JC, the explanatory assistant for JLIGHT Health Intelligence. "
                    "Explain only the supplied deterministic, de-identified evidence. "
                    "Do not diagnose, infer susceptibility, recommend treatment, change a "
                    "finding's status/severity, claim source validation, or make decisions. "
                    "Preserve every human-review requirement and uncertainty. If evidence is "
                    "insufficient, say so. Never request or infer patient/participant identity. "
                    "Keep the explanation concise and suitable for professional review."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"intent": intent, "evidence": dict(summary)}, separators=(",", ":")),
            },
        ],
    }
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read(128_000)
        envelope = json.loads(raw.decode("utf-8"))
        content = envelope["choices"][0]["message"]["content"]
        result = json.loads(content)
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, UnicodeDecodeError, json.JSONDecodeError):
        raise JCProviderUnavailable("JC language provider request failed") from None

    if not isinstance(result, dict) or set(result) != set(schema["required"]):
        raise JCProviderInvalidResponse("JC provider response did not match the required schema")
    if not isinstance(result["summary"], str) or len(result["summary"]) > 1200:
        raise JCProviderInvalidResponse("JC provider summary exceeded its response limit")
    for field in ("key_observations", "uncertainties", "limitations"):
        items = result[field]
        if not isinstance(items, list) or len(items) > 8 or any(
            not isinstance(item, str) or len(item) > 300 for item in items
        ):
            raise JCProviderInvalidResponse("JC provider list field exceeded its response limit")
    if not isinstance(result["human_review_required"], bool):
        raise JCProviderInvalidResponse("JC provider review flag is invalid")
    # The model may add a review requirement, but can never remove the engine's.
    result["human_review_required"] = bool(
        result["human_review_required"] or summary.get("human_review_required", False)
    )
    result["provider"] = "configured_language_model"
    result["model"] = model
    result["authoritative"] = False
    return result
