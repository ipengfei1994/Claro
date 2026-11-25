from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from claro.application.message_events import decode_event, encode_event
from claro.application.risk_events import (
    RISK_ASSESSED_EVENT,
    RiskAssessedPayload,
)
from claro.data_access.repositories.risk_repository import StoredRiskResult


def stored_result(*, risk_level: str = "high") -> StoredRiskResult:
    return StoredRiskResult(
        message_id=uuid4(),
        risk_result_id=uuid4(),
        risk_score=0.82,
        risk_level=risk_level,
        suggested_action="block",
        confidence=0.9,
        categories=[
            {
                "category": "spam_advertising",
                "db_category": "spam",
                "name": "Spam",
                "score": 0.82,
                "level": "high",
            },
            {
                "category": "normal",
                "db_category": None,
                "name": "Normal",
                "score": 0.0,
                "level": "normal",
            },
        ],
        detection_methods=["rule", "ml"],
        model_id="model-1",
        detected_at=datetime(2026, 11, 25, 12, 0, tzinfo=UTC),
        explanation={"summary": "test"},
        timings={"total": 3.0},
    )


def test_builds_risk_event_from_stored_result() -> None:
    stored = stored_result()
    payload = RiskAssessedPayload.from_stored(stored, synthetic=True)
    assert payload.message_id == stored.message_id
    assert payload.risk_result_id == stored.risk_result_id
    assert payload.synthetic is True
    assert payload.dataset_id is None
    assert len(payload.categories) == 1
    assert payload.categories[0].db_category == "spam"

    event = payload.to_event(trace_id="trace-1")
    assert event.event_id == stored.risk_result_id
    assert event.event_type == RISK_ASSESSED_EVENT
    assert event.trace_id == "trace-1"
    assert event.payload["detected_at"] == "2026-11-25T12:00:00Z"

    decoded = decode_event(encode_event(event))
    assert decoded.event_id == stored.risk_result_id
    assert decoded.payload["risk_result_id"] == str(stored.risk_result_id)
    assert decoded.payload["categories"][0]["score"] == 0.82


def test_dataset_can_be_attached_after_creation() -> None:
    payload = RiskAssessedPayload.from_stored(stored_result(), synthetic=True)
    dataset_id = uuid4()
    updated = payload.with_dataset(dataset_id)
    assert updated.dataset_id == dataset_id
    assert payload.dataset_id is None
    assert updated.to_event().payload["dataset_id"] == str(dataset_id)


def test_rejects_unknown_risk_level() -> None:
    with pytest.raises(ValueError, match="unknown risk level"):
        RiskAssessedPayload.from_stored(stored_result(risk_level="unknown"), synthetic=True)


def test_rejects_naive_detection_time() -> None:
    stored = replace(stored_result(), detected_at=datetime(2026, 11, 25, 12, 0))
    with pytest.raises(ValidationError, match="timezone-aware"):
        RiskAssessedPayload.from_stored(stored, synthetic=True)
