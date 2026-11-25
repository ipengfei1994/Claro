from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from claro.application.events import EventEnvelope
from claro.application.kafka_ingestion import KafkaIngestionService
from claro.application.message_events import (
    PERSISTED_GAME_MESSAGE_EVENT,
    PersistedGameMessagePayload,
    RawGameMessagePayload,
)
from claro.application.message_processing import (
    ORIGIN_OFFSET_HEADER,
    ORIGIN_PARTITION_HEADER,
    ORIGIN_RECEIVED_AT_HEADER,
    ORIGIN_TOPIC_HEADER,
    RETRY_COUNT_HEADER,
    ConsumedMessage,
    PermanentMessageError,
)
from claro.data_access.database import create_session_factory
from claro.data_access.models import (
    AuditEvent,
    Base,
    Dataset,
    InboxEvent,
    Message,
    ProcessingEvent,
)
from claro.data_access.repositories.synthetic_repository import load_generated_dataset
from claro.data_generation.generator import (
    GeneratedDataset,
    GenerationSpec,
    generate_synthetic_dataset,
)
from claro.infrastructure.kafka import KafkaDeliveryError


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    try:
        yield factory
    finally:
        engine.dispose()


class FakePublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, EventEnvelope]] = []
        self.fail_next = False

    def publish(self, topic: str, event: EventEnvelope, headers=None) -> None:
        if self.fail_next:
            self.fail_next = False
            raise KafkaDeliveryError("simulated processed-topic outage")
        self.events.append((topic, event))


def _generated() -> GeneratedDataset:
    return generate_synthetic_dataset(
        GenerationSpec(
            players=4,
            servers=1,
            alliances=2,
            messages=6,
            policy_rules=8,
            name="phase-02-kafka-unit",
        )
    )


def _consumed(index: int = 0) -> ConsumedMessage:
    record = _generated().messages[index]
    payload = RawGameMessagePayload.from_json_mapping(record.raw_payload())
    return ConsumedMessage(
        event=payload.to_event(sent_at=datetime(2026, 1, 2, 10, tzinfo=UTC)),
        topic="game.messages.raw",
        partition=1,
        offset=9,
        received_at=datetime(2026, 1, 2, 10, 1, tzinfo=UTC),
        headers={},
    )


def _service(
    session_factory: sessionmaker[Session], publisher: FakePublisher
) -> KafkaIngestionService:
    return KafkaIngestionService(session_factory, publisher, "game.messages.processed")


def test_ingestion_persists_atomically_and_emits_label_free_processed_event(
    session_factory: sessionmaker[Session],
) -> None:
    publisher = FakePublisher()
    consumed = _consumed()

    result = _service(session_factory, publisher).handle(consumed)

    assert result.status == "processed"
    with Session(session_factory.kw["bind"]) as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 1
        assert session.scalar(select(func.count()).select_from(InboxEvent)) == 1
        assert session.scalar(select(func.count()).select_from(ProcessingEvent)) == 1
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1
        message = session.scalar(select(Message))
        assert message is not None
        assert message.ingested_at == consumed.received_at
        assert message.is_synthetic is True
        inbox = session.scalar(select(InboxEvent))
        assert inbox is not None
        assert inbox.source_offset == 9
        assert inbox.status == "processed"
    assert len(publisher.events) == 1
    topic, event = publisher.events[0]
    assert topic == "game.messages.processed"
    assert event.event_type == PERSISTED_GAME_MESSAGE_EVENT
    processed = PersistedGameMessagePayload.model_validate_json(json.dumps(event.payload))
    assert processed.sent_at == consumed.event.occurred_at
    assert processed.received_at == consumed.received_at
    assert "content" not in event.payload
    assert "label" not in event.payload
    assert "risk_score" not in event.payload


def test_duplicate_delivery_does_not_duplicate_database_records(
    session_factory: sessionmaker[Session],
) -> None:
    publisher = FakePublisher()
    service = _service(session_factory, publisher)
    consumed = _consumed()

    assert service.handle(consumed).status == "processed"
    assert service.handle(consumed).status == "duplicate"

    with Session(session_factory.kw["bind"]) as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 1
        assert session.scalar(select(func.count()).select_from(InboxEvent)) == 1
        inbox = session.scalar(select(InboxEvent))
        assert inbox is not None
        assert inbox.attempts == 2
    assert len(publisher.events) == 2


def test_processed_publish_failure_is_retryable_without_losing_database_state(
    session_factory: sessionmaker[Session],
) -> None:
    publisher = FakePublisher()
    publisher.fail_next = True
    service = _service(session_factory, publisher)
    consumed = _consumed()

    with pytest.raises(KafkaDeliveryError, match="outage"):
        service.handle(consumed)
    result = service.handle(consumed)

    assert result.status == "duplicate"
    with Session(session_factory.kw["bind"]) as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 1
        assert session.scalar(select(func.count()).select_from(InboxEvent)) == 1
    assert len(publisher.events) == 1


def test_reused_event_id_with_different_content_is_rejected(
    session_factory: sessionmaker[Session],
) -> None:
    publisher = FakePublisher()
    service = _service(session_factory, publisher)
    consumed = _consumed()
    service.handle(consumed)
    raw = RawGameMessagePayload.from_json_mapping(_generated().messages[0].raw_payload())
    corrupted = raw.model_copy(
        update={
            "content": "不同内容",
            "content_hash": hashlib.sha256("不同内容".encode()).hexdigest(),
        }
    )
    conflicting = ConsumedMessage(
        event=corrupted.to_event(),
        topic=consumed.topic,
        partition=consumed.partition,
        offset=consumed.offset,
        received_at=consumed.received_at,
        headers={},
    )

    with pytest.raises(PermanentMessageError, match="different payload"):
        service.handle(conflicting)

    with Session(session_factory.kw["bind"]) as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 1
        assert session.scalar(select(func.count()).select_from(InboxEvent)) == 1


def test_retry_headers_preserve_original_source_coordinates(
    session_factory: sessionmaker[Session],
) -> None:
    publisher = FakePublisher()
    consumed = _consumed()
    retried = ConsumedMessage(
        event=consumed.event,
        topic="game.messages.retry",
        partition=2,
        offset=99,
        received_at=datetime(2026, 1, 2, 10, 2, tzinfo=UTC),
        headers={
            RETRY_COUNT_HEADER: "1",
            ORIGIN_TOPIC_HEADER: "game.messages.raw",
            ORIGIN_PARTITION_HEADER: "1",
            ORIGIN_OFFSET_HEADER: "9",
            ORIGIN_RECEIVED_AT_HEADER: consumed.received_at.isoformat(),
        },
    )

    result = _service(session_factory, publisher).handle(retried)

    assert result.status == "processed"
    with Session(session_factory.kw["bind"]) as session:
        inbox = session.scalar(select(InboxEvent))
        assert inbox is not None
        assert inbox.source_topic == "game.messages.raw"
        assert inbox.source_partition == 1
        assert inbox.source_offset == 9
        assert inbox.received_at == consumed.received_at
        assert inbox.attempts == 2


def test_kafka_ingestion_reuses_preloaded_message_without_duplicate_history(
    session_factory: sessionmaker[Session],
) -> None:
    generated = _generated()
    load_generated_dataset(session_factory, generated, batch_size=2)
    publisher = FakePublisher()

    result = _service(session_factory, publisher).handle(_consumed())

    assert result.status == "processed"
    with Session(session_factory.kw["bind"]) as session:
        assert session.scalar(select(func.count()).select_from(Message)) == len(generated.messages)
        assert session.scalar(select(func.count()).select_from(ProcessingEvent)) == 5 * len(
            generated.messages
        )
        assert session.scalar(select(func.count()).select_from(Dataset)) == 1
        audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "kafka_ingested"))
        assert audit is not None
        assert audit.details["message_preexisted"] is True


def test_source_offset_reuse_by_another_event_is_rejected(
    session_factory: sessionmaker[Session],
) -> None:
    publisher = FakePublisher()
    service = _service(session_factory, publisher)
    service.handle(_consumed(0))
    other = _consumed(1)

    with pytest.raises(PermanentMessageError, match="source offset"):
        service.handle(other)

    with Session(session_factory.kw["bind"]) as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 1
        assert session.scalar(select(func.count()).select_from(InboxEvent)) == 1
