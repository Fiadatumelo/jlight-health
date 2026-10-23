"""Explainable operational Decision Cards built only from observed source events.

These are workflow-monitoring signals, not diagnoses, laboratory interpretations, or
instructions to operate an analyser. Every card points to the exact source event evidence.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

TERMINAL = {"released", "cancelled", "admission_closed", "analysis_completed"}


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("observed_at must be a timezone-aware timestamp")
    if parsed.tzinfo is None:
        raise ValueError("observed_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def build_decision_cards(events: Iterable[Mapping[str, Any]], *,
                         now: datetime | None = None,
                         stall_after_minutes: int = 120) -> list[dict[str, Any]]:
    """Flag potentially stalled workflows using a configurable operational threshold."""
    if stall_after_minutes < 1:
        raise ValueError("stall_after_minutes must be positive")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for event in events:
        source_system = str(event.get("source_system") or "").strip()
        source_record_id = str(event.get("source_record_id") or "").strip()
        event_id = str(event.get("event_id") or "").strip()
        domain = str(event.get("domain") or "").strip().lower()
        if not all((source_system, source_record_id, event_id)):
            raise ValueError("events require source_system, source_record_id and event_id")
        if domain not in {"hospital", "laboratory", "bioinformatics"}:
            raise ValueError("unsupported domain; clinical trials remain separate")
        observed = _parse_timestamp(event.get("observed_at"))
        key = (source_system, source_record_id)
        groups.setdefault(key, []).append({**event, "_parsed_at": observed})

    cards = []
    for (source_system, source_record_id), items in groups.items():
        ordered = sorted(items, key=lambda item: (item["_parsed_at"], str(item["event_id"])))
        latest = ordered[-1]
        event_type = str(latest.get("event_type") or "")
        age_minutes = int((current - latest["_parsed_at"]).total_seconds() // 60)
        if event_type in TERMINAL or age_minutes < stall_after_minutes:
            continue
        evidence_ids = [str(item["event_id"]) for item in ordered]
        fingerprint = hashlib.sha256(
            f"workflow_stalled|{source_system}|{source_record_id}|{latest['event_id']}|{stall_after_minutes}".encode()
        ).hexdigest()
        cards.append({
            "card_id": fingerprint[:24],
            "card_type": "workflow_stalled",
            "state": "ATTENTION",
            "domain": latest.get("domain"),
            "title": "Workflow may be stalled",
            "issue": "No newer source-observed progress event has arrived within the configured monitoring window.",
            "why_it_matters": "A delay may indicate a queue, hand-off, integration, or source-system availability issue. The source system remains authoritative.",
            "what_changed": {
                "last_observed_event": event_type,
                "last_observed_at": latest["_parsed_at"].isoformat().replace("+00:00", "Z"),
                "minutes_since_last_event": age_minutes,
                "threshold_minutes": stall_after_minutes,
            },
            "suggested_step": "Check the source system and its integration/transfer status; confirm whether a newer event is available before taking operational action.",
            "confidence": "moderate",
            "limitations": [
                "This is an operational delay signal, not a clinical conclusion.",
                "The configured threshold may not fit every workflow.",
                "A delayed feed can look like a stalled workflow.",
            ],
            "evidence": [{
                "source_system": source_system,
                "source_record_id": source_record_id,
                "event_ids": evidence_ids,
                "latest_event_id": str(latest["event_id"]),
                "domain": latest.get("domain"),
            }],
            "source_values_modified": False,
            "human_review_required": True,
        })
    return sorted(cards, key=lambda card: (card["domain"], card["card_id"]))
