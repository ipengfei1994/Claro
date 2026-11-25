"""Dashboard rendering and report export integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from claro.analytics.definitions import PRIMARY_DATASET_NAME
from claro.analytics.filters import AnalyticsFilters
from claro.analytics.reports import ReportService, default_filters
from claro.analytics.services import AnalyticsService
from claro.bootstrap import AppContainer
from claro.ui.app import NAVIGATION

pytestmark = pytest.mark.integration

# Navigation moved from a radio group to ``st.navigation`` in Phase 06, so the
# analytics pages are discovered from the real navigation table instead of a
# hardcoded menu label. ``AppTest.switch_page`` resolves file paths relative to
# the main script and therefore cannot address ``st.navigation`` pages, so each
# screen module is rendered the same way ``app.py`` renders it.
ANALYTICS_SCREENS = tuple(
    renderer.__module__.rsplit(".", 1)[-1] for _, renderer, _ in NAVIGATION["分析"]
)


def _render(screen: str) -> None:
    import importlib

    from claro.ui.common import get_container

    importlib.import_module(f"claro.ui.screens.{screen}").render(get_container())


@pytest.mark.parametrize("screen", ANALYTICS_SCREENS)
def test_analytics_screen_renders_without_exceptions(screen: str) -> None:
    assert screen.startswith("analytics_"), screen
    app = AppTest.from_function(_render, args=(screen,), default_timeout=300)
    app.run()
    assert not app.exception, f"{screen}: {[str(item.value) for item in app.exception]}"
    assert not app.error, f"{screen}: {[item.value for item in app.error]}"


@pytest.mark.parametrize(
    "report_type",
    [
        "daily_risk",
        "weekly_risk",
        "governance_performance",
        "policy_evaluation",
        "model_performance",
    ],
)
def test_report_export_writes_markdown_and_csv(
    full_container: AppContainer, tmp_path: Path, report_type: str
) -> None:
    service = AnalyticsService(full_container.analytics_repository)
    report_service = ReportService(service, full_container.strategy_replay_service)
    filters = default_filters(days=365, dataset_name=PRIMARY_DATASET_NAME)
    report = report_service.generate(report_type, filters)
    files = report_service.export(report, tmp_path)
    assert len(files) >= 1
    assert files[0].suffix == ".md"
    assert "KPI 口径" in files[0].read_text(encoding="utf-8")
    csv_files = [item for item in files if item.suffix == ".csv"]
    for path in csv_files:
        assert path.stat().st_size > 0


def test_filter_summary_propagates_to_report_scope() -> None:
    filters = AnalyticsFilters(
        start="2026-01-01T00:00:00+00:00",  # type: ignore[arg-type]
        end="2026-02-01T00:00:00+00:00",  # type: ignore[arg-type]
        dataset_name=PRIMARY_DATASET_NAME,
        server_ref="s1",
    )
    summary = filters.summary()
    assert summary["server"] == "s1"
    assert summary["dataset"] == PRIMARY_DATASET_NAME
