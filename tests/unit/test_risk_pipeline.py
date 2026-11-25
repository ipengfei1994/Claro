from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from claro.application.events import EventEnvelope
from claro.application.message_events import PersistedGameMessagePayload
from claro.application.message_processing import (
    ConsumedMessage,
    PermanentMessageError,
)
from claro.application.risk_events import RISK_ASSESSED_EVENT
from claro.application.risk_pipeline import RiskPipelineService
from claro.application.risk_service import DetectionRecord, RiskServiceError
from claro.data_access.repositories.risk_repository import StoredRiskResult


@dataclass
class FakeService:
    record: DetectionRecord | None = None
    error: Exception | None = None
    calls: list[UUID] | None = None

    def __post_init__(self) -> None:
        self.calls = []

    def detect(self, message_id: UUID) -> DetectionRecord:
        self.calls.append(message_id)
        if self.error is not None:
            raise self.error
        assert self.record is not None
        return self.record


class FakePublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, EventEnvelope]] = []

    def publish(self, topic: str, event: EventEnvelope, headers=None) -> None:
        self.calls.append((topic, event))


def stored_result(message_id: UUID, *, created: bool) -> DetectionRecord:
    return DetectionRecord(
        stored=StoredRiskResult(
            message_id=message_id,
            risk_result_id=uuid4(),
            risk_score=0.9,
            risk_level="critical",
            suggested_action="restrict",
            confidence=0.95,
            categories=[
                {
                    "category": "fraud_fake_reward",
                    "db_category": "fraud",
                    "name": "Fraud",
                    "score": 0.9,
                    "level": "critical",
                }
            ],
            detection_methods=["rule"],
            model_id=None,
            detected_at=datetime(2026, 11, 25, 12, 0, tzinfo=UTC),
            explanation={},
            timings={},
        ),
        created=created,
    )


def consumed(message_id: UUID, dataset_id: UUID, event_type: str | None = None) -> ConsumedMessage:
    payload = PersistedGameMessagePayload(
        synthetic=True,
        dataset_id=dataset_id,
        message_id=message_id,
        external_message_id="ext-1",
        trace_id="trace-1",
        status="received",
        source_topic="game.messages.raw",
        source_partition=2,
        source_offset=17,
        sent_at=datetime(2026, 11, 25, 11, 59, tzinfo=UTC),
        received_at=datetime(2026, 11, 25, 11, 59, 1, tzinfo=UTC),
        persisted_at=datetime(2026, 11, 25, 11, 59, 2, tzinfo=UTC),
    )
    event = payload.to_event(datetime(2026, 11, 25, 12, 0, tzinfo=UTC))
    if event_type is not None:
        event = EventEnvelope(
            event_id=event.event_id,
            event_type=event_type,
            payload=event.payload,
            occurred_at=event.occurred_at,
            trace_id=event.trace_id,
            schema_version=event.schema_version,
        )
    return ConsumedMessage(
        event=event,
        topic="game.messages.persisted",
        partition=0,
        offset=99,
        received_at=datetime(2026, 11, 25, 12, 0, 1, tzinfo=UTC),
        headers={},
    )


def test_detects_and_publishes_committed_result() -> None:
    message_id = uuid4()
    dataset_id = uuid4()
    record = stored_result(message_id, created=True)
    service = FakeService(record=record)
    publisher = FakePublisher()
    pipeline = RiskPipelineService(service, publisher, "game.risk.assessed")

    result = pipeline.handle(consumed(message_id, dataset_id))

    assert result.status == "processed"
    assert service.calls == [message_id]
    assert len(publisher.calls) == 1
    topic, event = publisher.calls[0]
    assert topic == "game.risk.assessed"
    assert event.event_type == RISK_ASSESSED_EVENT
    assert event.event_id == record.stored.risk_result_id
    assert event.trace_id == "trace-1"
    assert event.payload["dataset_id"] == str(dataset_id)
    assert event.payload["synthetic"] is True


def test_duplicate_detection_still_publishes_stable_event() -> None:
    message_id = uuid4()
    record = stored_result(message_id, created=False)
    publisher = FakePublisher()
    pipeline = RiskPipelineService(FakeService(record=record), publisher, "risk")

    result = pipeline.handle(consumed(message_id, uuid4()))

    assert result.status == "duplicate"
    assert publisher.calls[0][1].event_id == record.stored.risk_result_id


def test_malformed_event_is_permanent() -> None:
    pipeline = RiskPipelineService(FakeService(), FakePublisher(), "risk")
    with pytest.raises(PermanentMessageError):
        pipeline.handle(consumed(uuid4(), uuid4(), event_type="game.message.raw.v1"))


def test_detection_failure_is_permanent() -> None:
    service = FakeService(error=RiskServiceError("message not found"))
    pipeline = RiskPipelineService(service, FakePublisher(), "risk")
    with pytest.raises(PermanentMessageError, match="message not found"):
        pipeline.handle(consumed(uuid4(), uuid4()))
