from __future__ import annotations

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from claro.data_access.database import create_session_factory
from claro.data_access.models import Base, Dataset, Message
from claro.data_access.seed import DATASET_NAME, seed_synthetic_data


def test_synthetic_seed_is_idempotent_and_traceable() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    first = seed_synthetic_data(session_factory)
    second = seed_synthetic_data(session_factory)

    assert first["created"] is True
    assert second["created"] is False
    assert second["messages"] == 3
    with Session(engine) as session:
        dataset = session.scalar(select(Dataset).where(Dataset.name == DATASET_NAME))
        assert dataset is not None
        assert dataset.is_synthetic
        assert dataset.seed == 20261124
        messages = list(session.scalars(select(Message).where(Message.dataset_id == dataset.id)))
        assert len(messages) == 3
        assert all(message.is_synthetic for message in messages)
        assert session.scalar(select(func.count()).select_from(Message)) == 3
    engine.dispose()
