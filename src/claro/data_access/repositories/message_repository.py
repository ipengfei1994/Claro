from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from claro.application.ports import MessageRepository
from claro.data_access.models import Message as MessageORM
from claro.domain.enums import MessageStatus
from claro.domain.message import Message


def _to_domain(record: MessageORM) -> Message:
    return Message(
        id=record.id,
        external_message_id=record.external_message_id,
        content=record.content,
        content_hash=record.content_hash,
        sender_ref=record.sender_ref,
        server_ref=record.server_ref,
        channel=record.channel,
        language=record.language,
        occurred_at=record.occurred_at,
        ingested_at=record.ingested_at,
        status=MessageStatus(record.status),
        dataset_id=record.dataset_id,
        is_synthetic=record.is_synthetic,
    )


class SqlAlchemyMessageRepository(MessageRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, message: Message) -> None:
        self.session.add(
            MessageORM(
                id=message.id,
                dataset_id=message.dataset_id,
                external_message_id=message.external_message_id,
                sender_ref=message.sender_ref,
                server_ref=message.server_ref,
                channel=message.channel,
                content=message.content,
                content_hash=message.content_hash,
                language=message.language,
                status=message.status.value,
                occurred_at=message.occurred_at,
                ingested_at=message.ingested_at,
                is_synthetic=message.is_synthetic,
            )
        )
        self.session.flush()

    def get(self, message_id: UUID) -> Message | None:
        record = self.session.get(MessageORM, message_id)
        return _to_domain(record) if record else None

    def get_by_external_id(self, external_message_id: str) -> Message | None:
        statement = select(MessageORM).where(MessageORM.external_message_id == external_message_id)
        record = self.session.scalar(statement)
        return _to_domain(record) if record else None

    def list_recent(self, limit: int = 20) -> Sequence[Message]:
        statement = select(MessageORM).order_by(MessageORM.ingested_at.desc()).limit(limit)
        return [_to_domain(record) for record in self.session.scalars(statement)]
