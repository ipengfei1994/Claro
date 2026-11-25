from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from claro.application.events import EventEnvelope

RAW_GAME_MESSAGE_EVENT = "game.message.raw.v1"


PERSISTED_GAME_MESSAGE_EVENT = "game.message.persisted.v1"


class MessageSerializationError(ValueError):
    pass


class RawGameMessagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    synthetic: bool
    dataset_id: UUID
    dataset_name: str = Field(min_length=1, max_length=120)
    dataset_seed: int = Field(ge=0)
    message_id: UUID
    external_message_id: str = Field(min_length=1, max_length=191)
    trace_id: str = Field(min_length=1, max_length=64)
    player_ref: str = Field(min_length=1, max_length=191)
    server_ref: str = Field(min_length=1, max_length=64)
    alliance_ref: str | None = Field(default=None, max_length=191)
    channel: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=1, max_length=10_000)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    language: str = Field(min_length=2, max_length=16)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def verify_content_hash(self) -> RawGameMessagePayload:
        expected = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if self.content_hash != expected:
            raise ValueError("content_hash does not match content")
        return self

    @classmethod
    def from_json_mapping(cls, payload: Mapping[str, Any]) -> RawGameMessagePayload:
        try:
            return cls.model_validate_json(json.dumps(payload, ensure_ascii=False, allow_nan=False))
        except (TypeError, ValueError) as error:
            raise MessageSerializationError(f"invalid raw game message: {error}") from error

    def to_event(self, sent_at: datetime | None = None) -> EventEnvelope:
        send_time = sent_at or datetime.now(UTC)
        if send_time.tzinfo is None or send_time.utcoffset() is None:
            raise ValueError("sent_at must be timezone-aware")
        return EventEnvelope(
            event_id=self.message_id,
            event_type=RAW_GAME_MESSAGE_EVENT,
            payload=self.model_dump(mode="json"),
            occurred_at=send_time,
            trace_id=self.trace_id,
        )


class PersistedGameMessagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    synthetic: bool
    dataset_id: UUID
    message_id: UUID
    external_message_id: str = Field(min_length=1, max_length=191)
    trace_id: str = Field(min_length=1, max_length=64)
    status: Literal["received", "processing", "decided", "closed"]
    source_topic: str = Field(min_length=1, max_length=191)
    source_partition: int = Field(ge=0)
    source_offset: int = Field(ge=0)
    sent_at: datetime
    received_at: datetime
    persisted_at: datetime

    @field_validator("sent_at", "received_at", "persisted_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @classmethod
    def from_json_mapping(cls, payload: Mapping[str, Any]) -> PersistedGameMessagePayload:
        try:
            return cls.model_validate_json(json.dumps(payload, ensure_ascii=False, allow_nan=False))
        except (TypeError, ValueError) as error:
            raise MessageSerializationError(f"invalid persisted game message: {error}") from error

    def to_event(self, sent_at: datetime | None = None) -> EventEnvelope:
        publish_time = sent_at or datetime.now(UTC)
        if publish_time.tzinfo is None or publish_time.utcoffset() is None:
            raise ValueError("sent_at must be timezone-aware")
        return EventEnvelope(
            event_id=self.message_id,
            event_type=PERSISTED_GAME_MESSAGE_EVENT,
            payload=self.model_dump(mode="json"),
            occurred_at=publish_time,
            trace_id=self.trace_id,
        )


def parse_raw_game_message(event: EventEnvelope) -> RawGameMessagePayload:
    if event.event_type != RAW_GAME_MESSAGE_EVENT:
        raise MessageSerializationError(
            f"expected {RAW_GAME_MESSAGE_EVENT}, received {event.event_type}"
        )
    try:
        message_id = UUID(str(event.payload.get("message_id")))
        if event.event_id != message_id:
            raise ValueError("event_id must match message_id")
        return RawGameMessagePayload.from_json_mapping(event.payload)
    except (TypeError, ValueError) as error:
        raise MessageSerializationError(f"invalid raw game message: {error}") from error


def parse_persisted_game_message(event: EventEnvelope) -> PersistedGameMessagePayload:
    if event.event_type != PERSISTED_GAME_MESSAGE_EVENT:
        raise MessageSerializationError(
            f"expected {PERSISTED_GAME_MESSAGE_EVENT}, received {event.event_type}"
        )
    try:
        message_id = UUID(str(event.payload.get("message_id")))
        if event.event_id != message_id:
            raise ValueError("event_id must match message_id")
        return PersistedGameMessagePayload.from_json_mapping(event.payload)
    except (TypeError, ValueError) as error:
        raise MessageSerializationError(f"invalid persisted game message: {error}") from error


def encode_event(event: EventEnvelope) -> bytes:
    try:
        return json.dumps(
            event.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise MessageSerializationError(f"event is not JSON serializable: {error}") from error


def decode_event(value: bytes | str | None) -> EventEnvelope:
    if value is None:
        raise MessageSerializationError("event value is missing")
    try:
        data: Any = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MessageSerializationError("event is not valid UTF-8 JSON") from error
    if not isinstance(data, dict):
        raise MessageSerializationError("event root must be an object")
    expected = {"event_id", "event_type", "schema_version", "occurred_at", "trace_id", "payload"}
    if set(data) != expected:
        raise MessageSerializationError("event fields do not match schema version 1")
    try:
        occurred_at = datetime.fromisoformat(data["occurred_at"])
        return EventEnvelope(
            event_id=UUID(data["event_id"]),
            event_type=data["event_type"],
            schema_version=data["schema_version"],
            payload=data["payload"],
            occurred_at=occurred_at,
            trace_id=data["trace_id"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise MessageSerializationError(f"invalid event envelope: {error}") from error
