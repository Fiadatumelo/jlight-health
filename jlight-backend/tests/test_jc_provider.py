"""Privacy and response-contract tests for the optional JC language adapter."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.jc_provider import (
    JCProviderInvalidResponse,
    JCProviderUnavailable,
    explain_jlight_evidence,
)


SAFE_SUMMARY = {
    "overall_status": "review_required",
    "finding_count": 1,
    "human_review_required": True,
    "findings": [{
        "finding_id": "bio_qc_001",
        "source": "bioinformatics",
        "severity": "medium",
        "status": "review",
        "evidence": {"qc_status": "review", "flag_count": 1},
        "requires_human_review": True,
    }],
    "limitations": ["A QC pass is not clinical validation."],
}


def _response(summary=None, review=False):
    body = {
        "summary": "One bioinformatics QC item requires review.",
        "key_observations": ["The supplied QC status is review."],
        "uncertainties": ["The source data have not been independently validated."],
        "human_review_required": review,
        "limitations": ["This is not a diagnosis."],
    }
    if summary:
        body.update(summary)
    envelope = {"choices": [{"message": {"content": json.dumps(body)}}]}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self, _limit): return json.dumps(envelope).encode()
    return Response()


def test_provider_missing_key_is_explicitly_unavailable(monkeypatch):
    monkeypatch.delenv("JLIGHT_JC_PROVIDER_API_KEY", raising=False)
    with pytest.raises(JCProviderUnavailable, match="not configured"):
        explain_jlight_evidence(SAFE_SUMMARY)


@pytest.mark.parametrize("key", ["patient_id", "participant_id", "mrn", "email", "raw_reads"])
def test_sensitive_evidence_fields_are_rejected(key, monkeypatch):
    monkeypatch.setenv("JLIGHT_JC_PROVIDER_API_KEY", "test-key")
    payload = dict(SAFE_SUMMARY)
    payload[key] = "sensitive"
    with pytest.raises(ValueError, match="Sensitive field"):
        explain_jlight_evidence(payload)


def test_identifier_like_evidence_text_is_rejected(monkeypatch):
    monkeypatch.setenv("JLIGHT_JC_PROVIDER_API_KEY", "test-key")
    payload = dict(SAFE_SUMMARY)
    payload["source_reference"] = "patient@example.org"
    with pytest.raises(ValueError, match="Potential identifier"):
        explain_jlight_evidence(payload)


def test_non_https_provider_endpoint_is_rejected(monkeypatch):
    monkeypatch.setenv("JLIGHT_JC_PROVIDER_API_KEY", "test-key")
    monkeypatch.setenv("JLIGHT_JC_PROVIDER_URL", "http://provider.invalid/v1")
    with pytest.raises(JCProviderUnavailable, match="HTTPS"):
        explain_jlight_evidence(SAFE_SUMMARY)


def test_valid_provider_response_cannot_clear_human_review(monkeypatch):
    monkeypatch.setenv("JLIGHT_JC_PROVIDER_API_KEY", "test-key")
    monkeypatch.delenv("JLIGHT_JC_PROVIDER_URL", raising=False)
    with patch("agent.jc_provider.urlopen", return_value=_response(review=False)) as call:
        result = explain_jlight_evidence(SAFE_SUMMARY, "explain_findings")
    assert result["human_review_required"] is True
    assert result["authoritative"] is False
    assert result["provider"] == "configured_language_model"
    request = call.call_args.args[0]
    assert isinstance(request, Request)
    sent = json.loads(request.data.decode())
    assert "patient_id" not in sent["messages"][1]["content"]
    assert sent["temperature"] == 0


def test_provider_cannot_add_unbounded_or_unknown_response_fields(monkeypatch):
    monkeypatch.setenv("JLIGHT_JC_PROVIDER_API_KEY", "test-key")
    with patch("agent.jc_provider.urlopen", return_value=_response({"patient_id": "x"})):
        with pytest.raises(JCProviderInvalidResponse):
            explain_jlight_evidence(SAFE_SUMMARY)


def test_only_supported_explanation_intents_are_accepted():
    with pytest.raises(ValueError, match="Unsupported"):
        explain_jlight_evidence(SAFE_SUMMARY, "make_a_diagnosis")



def test_provider_cannot_send_credentials_to_unapproved_https_host(monkeypatch):
    monkeypatch.setenv("JLIGHT_JC_PROVIDER_API_KEY", "test-key")
    monkeypatch.setenv("JLIGHT_JC_PROVIDER_URL", "https://attacker.invalid/v1")
    with pytest.raises(JCProviderUnavailable, match="approved OpenAI"):
        explain_jlight_evidence(SAFE_SUMMARY)
