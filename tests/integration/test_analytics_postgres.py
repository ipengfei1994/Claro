"""Integration tests for Phase 05 SQL executed against real PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from claro.analytics.definitions import PRIMARY_DATASET_NAME
from claro.analytics.filters import AnalyticsFilters
from claro.analytics.services import AnalyticsService
from claro.bootstrap import AppContainer

pytestmark = pytest.mark.integration


def _filters(**overrides: object) -> AnalyticsFilters:
    values: dict[str, object] = {
        "start": datetime(2026, 1, 1, tzinfo=UTC),
        "end": datetime(2026, 3, 1, tzinfo=UTC),
        "dataset_name": PRIMARY_DATASET_NAME,
    }
    values.update(overrides)
    return AnalyticsFilters(**values)  # type: ignore[arg-type]


def test_overview_and_time_series_match_generator_totals(full_container: AppContainer) -> None:
    service = AnalyticsService(full_container.analytics_repository)
    overview = service.overview(_filters())
    kpis = overview["kpis"]
    # Counts vary slightly when other integration tests add or remove synthetic
    # verification rows, so assert the cross-view invariants instead of a
    # brittle literal count. The hand-checkable literal cases live in unit tests.
    assert kpis["total_messages"] > 49_000
    assert kpis["risk_messages"] > 8_000
    assert kpis["risk_rate"]["risk_rate"] == round(
        kpis["risk_messages"] / kpis["total_messages"], 6
    )

    series = service.risk(_filters(), "day")["series"]
    assert sum(row["total_messages"] for row in series) == kpis["total_messages"]
    assert sum(row["risk_messages"] for row in series) == kpis["risk_messages"]


def test_category_and_dimension_filters_change_query_results(
    full_container: AppContainer,
) -> None:
    service = AnalyticsService(full_container.analytics_repository)
    baseline = service.overview(_filters())
    with full_container.engine.connect() as connection:
        server_ref = connection.execute(
            text("SELECT server_ref FROM message WHERE server_ref IS NOT NULL LIMIT 1")
        ).scalar_one()
    filtered = service.overview(_filters(server_ref=server_ref))
    assert 0 < filtered["kpis"]["total_messages"] < baseline["kpis"]["total_messages"]
    assert filtered["filters"]["server"] == server_ref

    categories = service.risk(_filters(), "day")["categories"]
    assert sum(row["message_count"] for row in categories) == baseline["kpis"]["risk_messages"]
    spam = service.risk(_filters(risk_category="spam"), "day")
    assert [row["category"] for row in spam["categories"]] == ["spam"]


def test_data_quality_queries_report_no_foreign_key_orphans(
    full_container: AppContainer,
) -> None:
    service = AnalyticsService(full_container.analytics_repository)
    quality = service.quality()
    error_checks = [check for check in quality["checks"] if check["severity"] == "error"]
    assert all(check["passed"] for check in error_checks)
    assert quality["definition_version"] == "phase-05.2"


def test_governance_and_model_queries_execute_with_explicit_limits(
    full_container: AppContainer,
) -> None:
    service = AnalyticsService(full_container.analytics_repository)
    governance = service.governance(_filters())
    assert governance["decisions"]["total_decisions"] > 0
    assert governance["moderation"]["human_review_duration_available"] is False

    model = service.model(_filters())
    assert model["runs"]
    assert model["observed_confusion"]["samples"] <= 7
    assert model["model_human_agreement"]["available"] is False


def test_join_does_not_inflate_message_counts(full_container: AppContainer) -> None:
    """One-to-many joins must not multiply the headline counts.

    The message-level metrics are recomputed with EXISTS/IN subqueries, which
    cannot fan out, and the results must be identical to the JOIN-based
    scoped CTE used by the production queries.
    """
    service = AnalyticsService(full_container.analytics_repository)
    kpis = service.overview(_filters())["kpis"]

    with full_container.engine.connect() as connection:
        window = (
            "m.occurred_at >= '2026-01-01' AND m.occurred_at < '2026-03-01' "
            f"AND d.name = '{PRIMARY_DATASET_NAME}'"
        )
        total = connection.execute(
            text(
                "SELECT COUNT(*) FROM message m JOIN dataset d ON d.id = m.dataset_id "
                f"WHERE {window}"
            )
        ).scalar_one()
        risk_exists = connection.execute(
            text(
                "SELECT COUNT(*) FROM message m JOIN dataset d ON d.id = m.dataset_id "
                f"WHERE {window} AND EXISTS "
                "(SELECT 1 FROM risk_event re WHERE re.message_id = m.id)"
            )
        ).scalar_one()
        risk_in = connection.execute(
            text(
                "SELECT COUNT(*) FROM message m JOIN dataset d ON d.id = m.dataset_id "
                f"WHERE {window} AND m.id IN (SELECT message_id FROM risk_event)"
            )
        ).scalar_one()

    assert kpis["total_messages"] == total
    assert kpis["risk_messages"] == risk_exists == risk_in
    assert kpis["risk_rate"]["risk_rate"] == round(risk_exists / total, 6)


def test_detection_quality_has_a_full_window_baseline(full_container: AppContainer) -> None:
    """Detection-layer false-positive and false-negative rates must be computable."""
    service = AnalyticsService(full_container.analytics_repository)
    overview = service.overview(_filters())
    kpis = overview["kpis"]
    assert kpis["detection_sample_size"] == kpis["total_messages"]
    assert kpis["false_positive_rate"] is not None
    assert kpis["false_negative_rate"] is not None
    assert 0.0 <= kpis["false_positive_rate"] <= 1.0
    assert 0.0 <= kpis["false_negative_rate"] <= 1.0

    # The confusion matrix must add up to the sample size.
    detection = service.governance(_filters())["detection_confusion"]
    assert (
        detection["true_positives"]
        + detection["false_positives"]
        + detection["false_negatives"]
        + detection["true_negatives"]
        == detection["samples"]
    )


def test_policy_rates_use_per_policy_denominators(full_container: AppContainer) -> None:
    """A scope-wide constant broadcast onto every policy row is not a metric."""
    strategy = AnalyticsService(full_container.analytics_repository).strategy(_filters())
    policies = [row for row in strategy["policies"] if row["replay_hit_messages"] > 0]
    assert policies
    automatic_denominators = {row["automatic_action_rate"]["denominator"] for row in policies}
    # Each policy is scored against its own hit count, so the denominators
    # must differ whenever the policies hit different numbers of messages.
    assert automatic_denominators <= {row["replay_hit_messages"] for row in policies}
    for row in policies:
        assert row["automatic_action_rate"]["denominator"] == row["replay_hit_messages"]
        assert row["manual_review_rate"]["denominator"] == row["replay_hit_messages"]


def test_low_sample_governance_ratios_are_not_published_as_values(
    full_container: AppContainer,
) -> None:
    """A ratio built from a handful of decisions must be unavailable, not 0.0."""
    service = AnalyticsService(full_container.analytics_repository)
    governance = service.governance(_filters())
    decisions = governance["decisions"]
    if decisions["eligible_finalized"] < 30:
        assert decisions["automatic_handling_rate"] is None
        assert decisions["automatic_handling_rate_detail"]["low_sample"] is True
        assert (
            decisions["automatic_handling_rate_detail"]["sample_size"]
            == (decisions["eligible_finalized"])
        )
    # The observed confusion slice is small and must be flagged.
    assert governance["observed_confusion"]["low_sample"] is True
    assert governance["observed_confusion"]["interpretable"] is False
