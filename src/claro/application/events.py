from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True)
class EventEnvelope:
    event_type: str
    payload: dict[str, Any]
    event_id: UUID = field(default_factory=uuid4)
    schema_version: int = 1
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    trace_id: str | None = None

    def __post_init__(self) -> None:
        if not self.event_type.strip():
            raise ValueError("event_type must not be empty")
        if not isinstance(self.payload, dict):
            raise ValueError("payload must be a mapping")
        if self.schema_version != 1:
            raise ValueError("schema_version must be 1")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at.isoformat(),
            "trace_id": self.trace_id,
            "payload": self.payload,
        }
