from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB

from claro.bootstrap import AppContainer
from claro.data_access.repositories.synthetic_repository import (
    check_dataset_quality,
    delete_synthetic_dataset,
    load_generated_dataset,
)
from claro.data_generation.generator import GenerationSpec, generate_synthetic_dataset


@pytest.mark.integration
def test_postgresql_phase_02_bulk_load_quality_and_cleanup(
    full_container: AppContainer,
) -> None:
    generated = generate_synthetic_dataset(
        GenerationSpec(
            name=f"phase-02-synthetic-integration-{uuid4()}",
            players=40,
            servers=2,
            alliances=4,
            messages=500,
            policy_rules=16,
        )
    )
    try:
        first = load_generated_dataset(full_container.session_factory, generated, batch_size=73)
        second = load_generated_dataset(full_container.session_factory, generated, batch_size=73)
        quality = check_dataset_quality(full_container.session_factory, generated.dataset.name)

        assert first["created"] is True
        assert second["created"] is False
        assert first["counts"]["messages"] == 500
        assert first["counts"]["processing_events"] == 2_500
        assert quality["passed"] is True
        player_columns = {
            column["name"]: column["type"]
            for column in inspect(full_container.engine).get_columns("player")
        }
        assert isinstance(player_columns["behavior_profile"], JSONB)
    finally:
        delete_synthetic_dataset(full_container.session_factory, generated.dataset.name)
