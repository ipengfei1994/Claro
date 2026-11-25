from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from sqlalchemy.orm import Session, sessionmaker

from claro.application.events import EventEnvelope
from claro.application.message_events import (
    PersistedGameMessagePayload,
    parse_raw_game_message,
)
from claro.application.message_processing import ConsumedMessage, HandlingResult
from claro.data_access.repositories.kafka_repository import (
    event_payload_hash,
    persist_raw_message,
)


class EventPublisher(Protocol):
    def publish(
        self,
        topic: str,
        event: EventEnvelope,
        headers: Mapping[str, str] | None = None,
    ) -> Any: ...


class KafkaIngestionService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        publisher: EventPublisher,
        processed_topic: str,
    ) -> None:
        self._session_factory = session_factory
        self._publisher = publisher
        self._processed_topic = processed_topic

    def handle(self, message: ConsumedMessage) -> HandlingResult:
        payload = parse_raw_game_message(message.event)
        result = persist_raw_message(
            self._session_factory,
            payload,
            source_topic=message.source_topic,
            source_partition=message.source_partition,
            source_offset=message.source_offset,
            payload_hash=event_payload_hash(message.event.to_dict()),
            sent_at=message.event.occurred_at,
            received_at=message.source_received_at,
            attempts=message.retry_count + 1,
        )
        processed = PersistedGameMessagePayload(
            synthetic=payload.synthetic,
            dataset_id=payload.dataset_id,
            message_id=payload.message_id,
            external_message_id=payload.external_message_id,
            trace_id=payload.trace_id,
            status=result.message_status,
            source_topic=message.source_topic,
            source_partition=message.source_partition,
            source_offset=message.source_offset,
            sent_at=message.event.occurred_at,
            received_at=message.source_received_at,
            persisted_at=result.persisted_at,
        )
        self._publisher.publish(self._processed_topic, processed.to_event())
        return HandlingResult(result.status)
