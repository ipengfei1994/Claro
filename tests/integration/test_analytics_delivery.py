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

pytestmark = pytest.mark.integration

ANALYTICS_PAGES = (
    "分析 · 总览",
    "分析 · 风险",
    "分析 · 社区",
    "分析 · 治理",
    "分析 · 模型",
    "分析 · 策略评估",
)


def test_all_analytics_pages_render_without_exceptions() -> None:
    app_path = Path(__file__).resolve().parents[2] / "src" / "claro" / "ui" / "app.py"
    for page in ANALYTICS_PAGES:
        app = AppTest.from_file(str(app_path), default_timeout=180)
        app.run()
        app.radio[0].set_value(page).run()
        assert not app.exception, f"{page}: {[str(item.value) for item in app.exception]}"


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
