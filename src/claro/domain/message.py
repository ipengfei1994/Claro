from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from claro.domain.enums import MessageStatus


@dataclass(frozen=True)
class Message:
    id: UUID
    external_message_id: str
    content: str
    content_hash: str
    sender_ref: str
    channel: str
    language: str
    occurred_at: datetime
    ingested_at: datetime
    status: MessageStatus = MessageStatus.RECEIVED
    dataset_id: UUID | None = None
    server_ref: str | None = None
    is_synthetic: bool = False
