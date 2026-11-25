from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from claro.data_access.database import create_session_factory
from claro.data_access.models import Base, Message
from claro.data_access.repositories.synthetic_repository import (
    check_dataset_quality,
    delete_synthetic_dataset,
    load_generated_dataset,
)
from claro.data_access.seed import seed_synthetic_data
from claro.data_generation.generator import (
    GeneratedDataset,
    GenerationSpec,
    generate_synthetic_dataset,
)


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    try:
        yield factory
    finally:
        engine.dispose()


def _generated() -> GeneratedDataset:
    return generate_synthetic_dataset(
        GenerationSpec(players=30, servers=3, alliances=6, messages=250, policy_rules=24)
    )


def test_bulk_load_is_idempotent_and_passes_data_quality(
    session_factory: sessionmaker[Session],
) -> None:
    generated = _generated()

    first = load_generated_dataset(session_factory, generated, batch_size=37)
    second = load_generated_dataset(session_factory, generated, batch_size=37)
    quality = check_dataset_quality(session_factory, generated.dataset.name)

    assert first["created"] is True
    assert second["created"] is False
    assert second["counts"] == first["counts"]
    assert first["counts"]["messages"] == 250
    assert first["counts"]["message_labels"] == 250
    assert first["counts"]["processing_events"] == 1_250
    assert first["counts"]["policy_rules"] == 24
    assert quality["passed"] is True
    assert all(quality["checks"].values())


def test_clean_replaces_only_the_selected_phase_02_dataset(
    session_factory: sessionmaker[Session],
) -> None:
    seed_synthetic_data(session_factory)
    generated = _generated()
    load_generated_dataset(session_factory, generated, batch_size=50)

    replacement = load_generated_dataset(session_factory, generated, batch_size=50, clean=True)
    deleted = delete_synthetic_dataset(session_factory, generated.dataset.name)

    assert replacement["created"] is True
    assert deleted == {"deleted": True, "dataset": generated.dataset.name}
    with Session(session_factory.kw["bind"]) as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 3
    with pytest.raises(ValueError, match="dataset not found"):
        check_dataset_quality(session_factory, generated.dataset.name)


def test_phase_01_dataset_is_protected_from_phase_02_cleanup(
    session_factory: sessionmaker[Session],
) -> None:
    seed_synthetic_data(session_factory)

    with pytest.raises(ValueError, match="only Phase 02 synthetic"):
        delete_synthetic_dataset(session_factory, "phase-01-synthetic-v1")


def test_invalid_batch_size_is_rejected(session_factory: sessionmaker[Session]) -> None:
    with pytest.raises(ValueError, match="batch_size"):
        load_generated_dataset(session_factory, _generated(), batch_size=0)
