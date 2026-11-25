from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from claro.data_access.database import create_session_factory
from claro.data_access.models import Base
from claro.data_access.repositories.message_repository import SqlAlchemyMessageRepository
from claro.domain.enums import MessageStatus
from claro.domain.message import Message


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as db_session:
        yield db_session
    engine.dispose()


def _message(external_id: str = "synthetic-0001") -> Message:
    now = datetime.now(UTC)
    return Message(
        id=uuid4(),
        external_message_id=external_id,
        content="Synthetic test message",
        content_hash="a" * 64,
        sender_ref="synthetic-player-1",
        channel="world",
        language="zh-CN",
        occurred_at=now,
        ingested_at=now,
        status=MessageStatus.RECEIVED,
        is_synthetic=True,
    )


def test_repository_round_trip_preserves_domain_message(session: Session) -> None:
    repository = SqlAlchemyMessageRepository(session)
    message = _message()
    repository.add(message)
    loaded = repository.get(message.id)
    assert loaded == message
    assert loaded.is_synthetic
    assert loaded.occurred_at.tzinfo == UTC


def test_external_message_id_is_unique(session: Session) -> None:
    repository = SqlAlchemyMessageRepository(session)
    repository.add(_message())
    with pytest.raises(IntegrityError):
        repository.add(_message())
    session.rollback()


def test_repository_lists_most_recent_first(session: Session) -> None:
    repository = SqlAlchemyMessageRepository(session)
    older = _message("synthetic-older")
    newer = _message("synthetic-newer")
    newer = replace(newer, ingested_at=datetime(2026, 1, 2, tzinfo=UTC))
    older = replace(older, ingested_at=datetime(2026, 1, 1, tzinfo=UTC))
    repository.add(newer)
    repository.add(older)
    assert [item.external_message_id for item in repository.list_recent()] == [
        "synthetic-newer",
        "synthetic-older",
    ]
