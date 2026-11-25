"""Strategy replay isolation and persistence tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import delete, select, text

from claro.analytics.definitions import PRIMARY_DATASET_NAME
from claro.analytics.filters import AnalyticsFilters
from claro.bootstrap import AppContainer
from claro.data_access.database import session_scope
from claro.data_access.models import AnalyticsReplayCase, AnalyticsReplayRun

pytestmark = pytest.mark.integration


def _filters() -> AnalyticsFilters:
    return AnalyticsFilters(
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 2, 1, tzinfo=UTC),
        dataset_name=PRIMARY_DATASET_NAME,
    )


def test_replay_is_isolated_from_formal_decisions(full_container: AppContainer) -> None:
    service = full_container.strategy_replay_service
    assert service is not None
    with full_container.engine.connect() as connection:
        before = tuple(
            connection.execute(
                text(
                    "SELECT (SELECT COUNT(*) FROM policy_decision), "
                    "(SELECT COUNT(*) FROM enforcement_action)"
                )
            ).one()
        )
    candidate = {
        "action_overrides": {"gov-critical-risk-review": "block"},
        "candidate_label": "integration-test",
    }
    result = service.run(_filters(), candidate, sample_limit=50, executed_by="integration-test")
    run_id = UUID(str(result["run_id"]))
    try:
        with full_container.engine.connect() as connection:
            after = tuple(
                connection.execute(
                    text(
                        "SELECT (SELECT COUNT(*) FROM policy_decision), "
                        "(SELECT COUNT(*) FROM enforcement_action)"
                    )
                ).one()
            )
        assert before == after
        assert result["sample_count"] == 50
        assert result["simulation"] is True
        assert result["low_sample"] is True
        assert result["differences"]["action_changes"] >= 0
        with session_scope(full_container.session_factory) as session:
            stored_run = session.get(AnalyticsReplayRun, run_id)
            cases = list(
                session.scalars(
                    select(AnalyticsReplayCase).where(AnalyticsReplayCase.run_id == run_id)
                )
            )
        assert stored_run is not None and stored_run.simulation is True
        assert stored_run.parameters["candidate"] == candidate
        assert len(cases) == 50
        assert all(case.input_snapshot for case in cases)
    finally:
        with session_scope(full_container.session_factory) as session:
            session.execute(delete(AnalyticsReplayRun).where(AnalyticsReplayRun.run_id == run_id))


def test_replay_comparison_uses_stored_metrics(full_container: AppContainer) -> None:
    service = full_container.strategy_replay_service
    assert service is not None
    comparison = service.compare()
    assert comparison["simulation"] is True
    assert comparison["runs"] or comparison["cases"] == []
