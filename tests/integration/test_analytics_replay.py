"""Strategy replay isolation and persistence tests."""

from __future__ import annotations

import hashlib
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

# Every business table a replay must never write to.
BUSINESS_TABLES = (
    "message",
    "risk_event",
    "risk_result",
    "policy_decision",
    "policy_evaluation",
    "moderation_case",
    "moderation_review",
    "enforcement_action",
    "governance_feedback",
)


def _content_fingerprint(connection, table: str) -> str:
    """Hash every row so an in-place edit is detected, not just a row count."""
    digest = hashlib.sha256()
    for (row,) in connection.execute(text(f"SELECT t::text FROM {table} t ORDER BY 1")):
        digest.update(row.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


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


def test_replay_leaves_business_tables_byte_identical(full_container: AppContainer) -> None:
    """Isolation must hold at content level, not only at row-count level.

    A replay that edited a decision in place would keep the row count intact,
    so the fingerprint below hashes every row of every business table.
    """
    service = full_container.strategy_replay_service
    assert service is not None
    with full_container.engine.connect() as connection:
        before = {table: _content_fingerprint(connection, table) for table in BUSINESS_TABLES}

    result = service.run(
        _filters(),
        {"action_overrides": {"gov-critical-risk-review": "block"}, "candidate_label": "iso"},
        sample_limit=200,
        executed_by="isolation-test",
    )
    run_id = UUID(str(result["run_id"]))
    try:
        with full_container.engine.connect() as connection:
            after = {table: _content_fingerprint(connection, table) for table in BUSINESS_TABLES}
        for table in BUSINESS_TABLES:
            assert before[table] == after[table], f"{table} was modified by the replay"
    finally:
        with session_scope(full_container.session_factory) as session:
            session.execute(delete(AnalyticsReplayRun).where(AnalyticsReplayRun.run_id == run_id))


def test_replay_pool_includes_clean_messages_so_false_positives_are_measurable(
    full_container: AppContainer,
) -> None:
    """The sample pool must contain true negatives.

    If the pool only contained messages the risk engine had already flagged,
    every message would be predicted positive and a false-positive rate could
    never be computed at all.
    """
    service = full_container.strategy_replay_service
    assert service is not None
    result = service.run(
        _filters(),
        {"candidate_label": "pool-check"},
        sample_limit=300,
        executed_by="pool-test",
    )
    run_id = UUID(str(result["run_id"]))
    try:
        pool = result["sample_pool"]
        assert pool["without_risk_event"] > 0
        assert pool["truth_negatives"] > 0
        metrics = result["baseline"]["metrics"]
        assert metrics["true_negatives"] > 0
        assert metrics["false_positive_rate"] is not None
        assert 0.0 <= metrics["false_positive_rate"] <= 1.0
    finally:
        with session_scope(full_container.session_factory) as session:
            session.execute(delete(AnalyticsReplayRun).where(AnalyticsReplayRun.run_id == run_id))


def test_replay_metrics_match_an_independent_recomputation(
    full_container: AppContainer,
) -> None:
    """The stored confusion matrix must equal a per-case recomputation."""
    from claro.analytics.metrics import predicted_positive, truth_positive

    service = full_container.strategy_replay_service
    assert service is not None
    result = service.run(
        _filters(),
        {"action_overrides": {"gov-critical-risk-review": "block"}, "candidate_label": "recompute"},
        sample_limit=200,
        executed_by="recompute-test",
    )
    run_id = UUID(str(result["run_id"]))
    try:
        with full_container.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT baseline_action, truth_label FROM analytics_replay_case "
                    "WHERE run_id = :run_id"
                ),
                {"run_id": run_id},
            ).all()
        matrix = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
        for action, label in rows:
            truth = truth_positive(label)
            predicted = predicted_positive(action)
            if truth and predicted:
                matrix["tp"] += 1
            elif not truth and predicted:
                matrix["fp"] += 1
            elif truth and not predicted:
                matrix["fn"] += 1
            else:
                matrix["tn"] += 1
        metrics = result["baseline"]["metrics"]
        assert metrics["true_positives"] == matrix["tp"]
        assert metrics["false_positives"] == matrix["fp"]
        assert metrics["false_negatives"] == matrix["fn"]
        assert metrics["true_negatives"] == matrix["tn"]
    finally:
        with session_scope(full_container.session_factory) as session:
            session.execute(delete(AnalyticsReplayRun).where(AnalyticsReplayRun.run_id == run_id))


def test_replay_reports_per_policy_effectiveness(full_container: AppContainer) -> None:
    """Each policy must be scored on its own, not aggregated into one number."""
    service = full_container.strategy_replay_service
    assert service is not None
    result = service.run(
        _filters(),
        {"candidate_label": "policy-effectiveness"},
        sample_limit=300,
        executed_by="policy-test",
    )
    run_id = UUID(str(result["run_id"]))
    try:
        rows = result["baseline"]["policy_effectiveness"]
        assert rows
        keys = {row["policy_key"] for row in rows}
        assert len(keys) == len(rows)
        for row in rows:
            assert "precision" in row
            assert "false_positive_rate" in row
            assert "false_negative_rate" in row
            assert "manual_review_rate" in row
            if not row["acts_on_risk"]:
                # A policy that never acts has no detection performance.
                assert row["precision"] is None
                assert row["recall"] is None
    finally:
        with session_scope(full_container.session_factory) as session:
            session.execute(delete(AnalyticsReplayRun).where(AnalyticsReplayRun.run_id == run_id))
