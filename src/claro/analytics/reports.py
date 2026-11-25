"""Reusable analytical report generation and CSV export.

Excel/PDF export is intentionally absent: the project does not ship openpyxl
or reportlab, and the Phase 05 constraint forbids adding heavy dependencies
purely for export. CSV and Markdown are produced from real analysis results.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from claro.analytics.filters import AnalyticsFilters
from claro.analytics.services import AnalyticsService
from claro.analytics.strategy import StrategyReplayService

REPORT_TYPES = (
    "daily_risk",
    "weekly_risk",
    "governance_performance",
    "policy_evaluation",
    "model_performance",
)


class ReportService:
    """Assemble reports from the same service results used by the dashboard."""

    def __init__(
        self, analytics: AnalyticsService, replay: StrategyReplayService | None = None
    ) -> None:
        self._analytics = analytics
        self._replay = replay

    def generate(self, report_type: str, filters: AnalyticsFilters) -> dict[str, Any]:
        if report_type not in REPORT_TYPES:
            raise ValueError(f"unsupported report type: {report_type}")
        generated_at = datetime.now(UTC)
        overview = self._analytics.overview(filters)
        quality = self._analytics.quality()
        if report_type in ("daily_risk", "weekly_risk"):
            risk = self._analytics.risk(filters, "day" if report_type == "daily_risk" else "week")
            sections = {
                "core_metrics": overview["kpis"],
                "risk_distribution": risk["categories"],
                "severity_distribution": risk["severities"],
                "time_series": risk["series"],
            }
            findings = [
                f"风险消息 {overview['kpis']['risk_messages']} 条，"
                f"风险率 {overview['kpis']['risk_rate']['risk_rate']}。",
                f"高风险消息 {overview['kpis']['high_risk_messages']} 条。",
                "风险事件与决策均为合成快照，不代表真实线上运营。",
            ]
        elif report_type == "governance_performance":
            governance = self._analytics.governance(filters)
            sections = {
                "core_metrics": governance["decisions"],
                "action_distribution": governance["decision_distribution"],
                "moderation": governance["moderation"],
                "enforcement": governance["enforcement"],
            }
            findings = [
                f"治理决策 {governance['decisions']['total_decisions']} 条；"
                f"有状态记录 {governance['decisions']['eligible_finalized']} 条。",
                f"审核任务完成 {governance['moderation']['completed_tasks']} / "
                f"{governance['moderation']['total_tasks']}。",
                "人工审核与反馈数据为空，人工推翻率及线上误杀/漏判不可计算。",
            ]
        elif report_type == "policy_evaluation":
            strategy = self._analytics.strategy(filters)
            sections = {
                "policy_ranking": strategy["policies"],
                "action_distribution": strategy["action_distribution"],
                "version_comparison": strategy["version_comparison"],
            }
            findings = [
                "命中率的分母为有策略评估记录的消息数，不是策略准确率。",
                "当前所有策略仅有 v1；版本差异请使用 Strategy Replay。",
            ]
        else:
            model = self._analytics.model(filters)
            sections = {
                "runs": model["runs"],
                "per_category": model["per_category"],
                "error_cases": model["error_cases"],
                "observed_confusion": model["observed_confusion"],
            }
            findings = [
                "指标来自持久化 evaluation_run，标签为合成 ground truth。",
                "缺少人工标签，不提供模型-人工一致率。",
            ]
        return {
            "report_type": report_type,
            "generated_at": generated_at.isoformat(),
            "data_window": filters.summary(),
            "dataset_version": filters.dataset_name or "all datasets",
            "definition": self._analytics.definition,
            "executive_summary": "；".join(findings),
            "sections": sections,
            "data_quality": {
                "passed": quality["passed"],
                "failed": quality["failed"],
                "warnings": quality["warnings"],
            },
            "limitations": [
                "所有记录均为 Synthetic Data。",
                "风险率统一使用 message.occurred_at 时间轴与去重消息数。",
                "Excel/PDF 导出未实现：项目未安装对应依赖，且不为导出引入大型依赖。",
            ],
            "recommendations": [
                "补充 moderation_review 与 governance_feedback 后启用人工一致性与线上误杀分析。",
                "历史策略多版本积累后启用真实版本对比。",
                "Hive 引擎可用后再验证离线分层结果。",
            ],
        }

    def render_markdown(self, report: dict[str, Any]) -> str:
        """Render a report as readable Markdown with explicit sections."""
        lines = [
            f"# Claro 分析报告 — {report['report_type']}",
            "",
            f"- 生成时间：{report['generated_at']}",
            f"- 数据窗口：{report['data_window']['start']} → {report['data_window']['end']}",
            f"- 数据集：{report['dataset_version']}",
            f"- KPI 口径：{report['definition']['version']} / {report['definition']['hash']}",
            "",
            "## 1. 执行摘要",
            "",
            report["executive_summary"],
            "",
            "## 2. 指标定义",
            "",
            "口径以 `docs/KPI_DEFINITIONS.md` 为唯一来源；本文件不重复定义公式。",
            "",
            "## 3. 核心指标与分析结果",
            "",
            "```json",
            _json_block(report["sections"]),
            "```",
            "",
            "## 4. 数据质量",
            "",
            str(report["data_quality"]),
            "",
            "## 5. 分析局限",
            "",
        ]
        lines.extend(f"- {item}" for item in report["limitations"])
        lines.extend(["", "## 6. 改进建议", ""])
        lines.extend(f"- {item}" for item in report["recommendations"])
        lines.append("")
        return "\n".join(lines)

    def export(self, report: dict[str, Any], output_dir: Path) -> list[Path]:
        """Write Markdown report and CSV tables derived from real results."""
        output_dir.mkdir(parents=True, exist_ok=True)
        generated = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        markdown_path = output_dir / f"{report['report_type']}-{generated}.md"
        markdown_path.write_text(self.render_markdown(report), encoding="utf-8")
        written = [markdown_path]
        for name, value in report["sections"].items():
            if not isinstance(value, list) or not value:
                continue
            if not all(isinstance(item, dict) for item in value):
                continue
            csv_path = output_dir / f"{report['report_type']}-{name}-{generated}.csv"
            _write_csv(csv_path, value)
            written.append(csv_path)
        return written


def _json_block(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write a flat CSV, converting nested values to JSON text."""
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: _json_block(value) if isinstance(value, (dict, list)) else value
                    for key, value in row.items()
                }
            )


def default_filters(days: int = 365, *, dataset_name: str | None = None) -> AnalyticsFilters:
    """Build filters ending at the current UTC moment."""
    end = datetime.now(UTC)
    filters = AnalyticsFilters(start=end - timedelta(days=days), end=end)
    if dataset_name:
        # Dataset name is resolved by the service layer; no hardcoded UUID.
        return filters.with_dataset(None, dataset_name)
    return filters
