from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from claro.application.message_events import RAW_GAME_MESSAGE_EVENT, RawGameMessagePayload
from claro.application.message_processing import PermanentMessageError
from claro.data_access.database import session_scope
from claro.data_access.models import (
    Alliance,
    AuditEvent,
    Dataset,
    InboxEvent,
    Message,
    Player,
    ProcessingEvent,
    Server,
)
from claro.domain.enums import MessageStatus, ProcessingStage, ProcessingStatus


@dataclass(frozen=True, slots=True)
class IngestionResult:
    status: Literal["processed", "duplicate"]
    message_id: UUID
    message_status: str
    persisted_at: datetime


def persist_raw_message(
    session_factory: sessionmaker[Session],
    payload: RawGameMessagePayload,
    *,
    source_topic: str,
    source_partition: int,
    source_offset: int,
    payload_hash: str,
    sent_at: datetime,
    received_at: datetime,
    attempts: int,
) -> IngestionResult:
    if source_partition < 0 or source_offset < 0:
        raise PermanentMessageError("Kafka source partition and offset must not be negative")
    if attempts < 1:
        raise PermanentMessageError("attempts must be positive")
    if len(payload_hash) != 64:
        raise PermanentMessageError("payload_hash must be a SHA-256 digest")
    for timestamp in (sent_at, received_at):
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise PermanentMessageError("Kafka timestamps must be timezone-aware")

    with session_scope(session_factory) as session:
        return _persist_in_session(
            session,
            payload,
            source_topic=source_topic,
            source_partition=source_partition,
            source_offset=source_offset,
            payload_hash=payload_hash,
            sent_at=sent_at,
            received_at=received_at,
            attempts=attempts,
        )


def _persist_in_session(
    session: Session,
    payload: RawGameMessagePayload,
    *,
    source_topic: str,
    source_partition: int,
    source_offset: int,
    payload_hash: str,
    sent_at: datetime,
    received_at: datetime,
    attempts: int,
) -> IngestionResult:
    processed_at = datetime.now(UTC)
    inbox = session.get(InboxEvent, payload.message_id)
    if inbox is not None:
        if inbox.payload_hash != payload_hash or inbox.event_type != RAW_GAME_MESSAGE_EVENT:
            raise PermanentMessageError("event_id was reused with a different payload")
        inbox.attempts = max(inbox.attempts + 1, attempts)
        session.flush()
        message = session.get(Message, payload.message_id)
        if message is None:
            raise PermanentMessageError("processed inbox event has no matching message")
        return IngestionResult(
            "duplicate", message.id, message.status, inbox.processed_at or processed_at
        )

    source_event = session.scalar(
        select(InboxEvent).where(
            InboxEvent.source_topic == source_topic,
            InboxEvent.source_partition == source_partition,
            InboxEvent.source_offset == source_offset,
        )
    )
    if source_event is not None:
        raise PermanentMessageError("Kafka source offset was reused by a different event")

    dataset = _ensure_dataset(session, payload)
    message = session.get(Message, payload.message_id)
    created_message = message is None
    if message is None:
        message = session.scalar(
            select(Message).where(Message.external_message_id == payload.external_message_id)
        )
        if message is not None:
            raise PermanentMessageError("external_message_id was reused by a different event")
        message = Message(
            id=payload.message_id,
            dataset_id=dataset.id,
            player_id=_entity_id(session, Player, dataset.id, "player_ref", payload.player_ref),
            server_id=_entity_id(session, Server, dataset.id, "server_ref", payload.server_ref),
            alliance_id=(
                _entity_id(session, Alliance, dataset.id, "alliance_ref", payload.alliance_ref)
                if payload.alliance_ref
                else None
            ),
            external_message_id=payload.external_message_id,
            sender_ref=payload.player_ref,
            server_ref=payload.server_ref,
            channel=payload.channel,
            content=payload.content,
            content_hash=payload.content_hash,
            language=payload.language,
            status=MessageStatus.RECEIVED.value,
            occurred_at=payload.occurred_at,
            ingested_at=received_at,
            is_synthetic=payload.synthetic,
        )
        session.add(message)
        session.flush()
    else:
        _verify_existing_message(message, payload)

    ingestion_event = session.scalar(
        select(ProcessingEvent).where(
            ProcessingEvent.message_id == message.id,
            ProcessingEvent.sequence == 1,
        )
    )
    if ingestion_event is None:
        session.add(
            ProcessingEvent(
                message_id=message.id,
                trace_id=payload.trace_id,
                sequence=1,
                stage=ProcessingStage.INGESTION.value,
                status=ProcessingStatus.SUCCEEDED.value,
                started_at=received_at,
                finished_at=processed_at,
                details={
                    "synthetic": payload.synthetic,
                    "transport": "kafka",
                    "source_topic": source_topic,
                    "source_partition": source_partition,
                    "source_offset": source_offset,
                    "sent_at": sent_at.isoformat(),
                    "received_at": received_at.isoformat(),
                },
            )
        )
    elif ingestion_event.stage != ProcessingStage.INGESTION.value:
        raise PermanentMessageError("message sequence 1 is not an ingestion event")

    session.add(
        InboxEvent(
            event_id=payload.message_id,
            event_type=RAW_GAME_MESSAGE_EVENT,
            source_topic=source_topic,
            source_partition=source_partition,
            source_offset=source_offset,
            payload_hash=payload_hash,
            status="processed",
            attempts=attempts,
            received_at=received_at,
            processed_at=processed_at,
            is_synthetic=payload.synthetic,
        )
    )
    session.add(
        AuditEvent(
            entity_type="message",
            entity_id=message.id,
            action="kafka_ingested",
            actor_type="system",
            actor_ref="kafka.consumer",
            trace_id=payload.trace_id,
            details={
                "synthetic": payload.synthetic,
                "dataset_id": str(dataset.id),
                "source_topic": source_topic,
                "source_partition": source_partition,
                "source_offset": source_offset,
                "message_preexisted": not created_message,
            },
        )
    )
    session.flush()
    return IngestionResult("processed", message.id, message.status, processed_at)


def _ensure_dataset(session: Session, payload: RawGameMessagePayload) -> Dataset:
    dataset = session.get(Dataset, payload.dataset_id)
    if dataset is not None:
        if dataset.name != payload.dataset_name or dataset.is_synthetic != payload.synthetic:
            raise PermanentMessageError("dataset metadata does not match the existing dataset")
        return dataset
    existing_name = session.scalar(select(Dataset).where(Dataset.name == payload.dataset_name))
    if existing_name is not None:
        raise PermanentMessageError("dataset name is already registered with a different ID")
    dataset = Dataset(
        id=payload.dataset_id,
        name=payload.dataset_name,
        seed=payload.dataset_seed,
        generation_params={
            "synthetic": payload.synthetic,
            "source": "kafka",
            "seed": payload.dataset_seed,
        },
        is_synthetic=payload.synthetic,
    )
    session.add(dataset)
    session.flush()
    return dataset


def _verify_existing_message(message: Message, payload: RawGameMessagePayload) -> None:
    if message.external_message_id != payload.external_message_id:
        raise PermanentMessageError("message_id does not match external_message_id")
    if message.dataset_id is not None and message.dataset_id != payload.dataset_id:
        raise PermanentMessageError("message_id belongs to a different dataset")
    if message.content_hash != payload.content_hash or message.content != payload.content:
        raise PermanentMessageError("message_id was reused with different content")
    if message.is_synthetic != payload.synthetic:
        raise PermanentMessageError("message synthetic marker does not match the event")


def _entity_id(
    session: Session,
    model: type[Player] | type[Server] | type[Alliance],
    dataset_id: UUID,
    reference_field: str,
    reference: str,
) -> UUID | None:
    column = getattr(model, reference_field)
    return session.scalar(
        select(model.id).where(model.dataset_id == dataset_id, column == reference)
    )


def event_payload_hash(event_dict: dict[str, Any]) -> str:
    encoded = json.dumps(event_dict, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
