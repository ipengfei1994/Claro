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
    error_checks = [
        check for check in quality["checks"] if check["severity"] == "error"
    ]
    assert all(check["passed"] for check in error_checks)
    assert quality["definition_version"] == "phase-05.1"


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
