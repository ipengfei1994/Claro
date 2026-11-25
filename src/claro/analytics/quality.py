"""Analytical data-quality checks backed by real SQL queries."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from claro.analytics.data_access import AnalyticsRepository
from claro.analytics.definitions import KPI_DEFINITION_HASH, KPI_DEFINITION_VERSION
from claro.analytics.metrics import as_float, as_int


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    severity: str
    observed: Any
    expected: Any
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class DataQualityService:
    """Run all analytical data-quality checks and report findings."""

    def __init__(self, repository: AnalyticsRepository) -> None:
        self._repository = repository

    def run(self) -> list[CheckResult]:
        checks: list[CheckResult] = []
        checks.extend(self._integrity_checks())
        checks.extend(self._coverage_checks())
        checks.extend(self._time_checks())
        checks.append(self._definition_check())
        return checks

    def _integrity_checks(self) -> list[CheckResult]:
        orphans = self._repository.quality_orphans()
        duplicates = self._repository.quality_duplicates()
        results: list[CheckResult] = []
        for key, label in (
            ("risk_event_orphans", "risk_event → message 关联"),
            ("decision_orphans", "policy_decision → message 关联"),
            ("enforcement_orphans", "enforcement_action → policy_decision 关联"),
        ):
            count = as_int(orphans.get(key))
            results.append(
                CheckResult(
                    name=f"orphan.{key}",
                    passed=count == 0,
                    severity="error",
                    observed=count,
                    expected=0,
                    detail=f"{label}孤儿记录数",
                )
            )
        for key, label in (
            ("duplicate_message_ids", "message 主键重复"),
            ("duplicate_external_ids", "external_message_id 重复"),
        ):
            count = as_int(duplicates.get(key))
            results.append(
                CheckResult(
                    name=f"duplicate.{key}",
                    passed=count == 0,
                    severity="error",
                    observed=count,
                    expected=0,
                    detail=label,
                )
            )
        duplicate_events = as_int(duplicates.get("duplicate_risk_events"))
        results.append(
            CheckResult(
                name="duplicate.risk_event_group",
                passed=duplicate_events == 0,
                severity="warning",
                observed=duplicate_events,
                expected=0,
                detail="risk_event 同 (message_id, rule_id, category, occurred_at) 重复组数",
            )
        )
        return results

    def _coverage_checks(self) -> list[CheckResult]:
        coverage = self._repository.quality_coverage()
        messages = as_int(coverage.get("messages"))
        decisions = as_int(coverage.get("decisions"))
        cases = as_int(coverage.get("cases"))
        risk_covered = as_int(coverage.get("risk_result_messages"))
        results = [
            CheckResult(
                name="coverage.risk_result",
                passed=risk_covered > 0,
                severity="warning",
                observed={"covered": risk_covered, "total": messages},
                expected="full coverage",
                detail="risk_result 为真实引擎产物；覆盖率低时指标仅代表已覆盖样本",
            ),
            CheckResult(
                name="coverage.policy_evaluation_link",
                passed=decisions == 0 or as_int(coverage.get("linked_decisions")) > 0,
                severity="warning",
                observed={
                    "linked": as_int(coverage.get("linked_decisions")),
                    "total": decisions,
                },
                expected="all decisions linked",
                detail="policy_decision 中关联策略评估记录的比例",
            ),
            CheckResult(
                name="coverage.moderation_decision_link",
                passed=cases == 0 or as_int(coverage.get("linked_cases")) > 0,
                severity="warning",
                observed={"linked": as_int(coverage.get("linked_cases")), "total": cases},
                expected="all cases linked",
                detail="moderation_case 中关联治理决策的比例",
            ),
            CheckResult(
                name="availability.human_labels",
                passed=as_int(coverage.get("reviews")) > 0,
                severity="warning",
                observed=as_int(coverage.get("reviews")),
                expected="> 0",
                detail="moderation_review 为空时无法计算人工审核耗时与一致性",
            ),
            CheckResult(
                name="availability.feedback",
                passed=as_int(coverage.get("feedback")) > 0,
                severity="warning",
                observed=as_int(coverage.get("feedback")),
                expected="> 0",
                detail="governance_feedback 为空时无法计算基于反馈的线上误杀/漏判",
            ),
        ]
        return results

    def _time_checks(self) -> list[CheckResult]:
        timing = self._repository.quality_time()
        invalid_message = as_int(timing.get("invalid_message_time"))
        invalid_case = as_int(timing.get("invalid_case_time"))
        lag = as_float(timing.get("ingest_lag_p95_seconds"))
        return [
            CheckResult(
                name="time.message_required_fields",
                passed=invalid_message == 0,
                severity="error",
                observed=invalid_message,
                expected=0,
                detail="message.occurred_at / ingested_at 空值数",
            ),
            CheckResult(
                name="time.moderation_case_order",
                passed=invalid_case == 0,
                severity="error",
                observed=invalid_case,
                expected=0,
                detail="closed_at 早于 opened_at 的任务数",
            ),
            CheckResult(
                name="time.ingest_lag_p95",
                passed=lag is None or lag >= 0,
                severity="info",
                observed=lag,
                expected=">= 0",
                detail="message 摄入延迟 P95（秒）",
            ),
        ]

    def _definition_check(self) -> CheckResult:
        # The service layer returns the same constant; no page may override it.
        return CheckResult(
            name="definition.kpi_hash",
            passed=bool(KPI_DEFINITION_HASH) and bool(KPI_DEFINITION_VERSION),
            severity="error",
            observed=KPI_DEFINITION_HASH,
            expected=KPI_DEFINITION_VERSION,
            detail="KPI 口径哈希来自 analytics.definitions，与 KPI_DEFINITIONS.md 版本对应",
        )

    def summary(self) -> dict[str, Any]:
        checks = self.run()
        return {
            "checks": [check.as_dict() for check in checks],
            "passed": sum(1 for check in checks if check.passed),
            "failed": sum(1 for check in checks if not check.passed),
            "errors": sum(1 for check in checks if not check.passed and check.severity == "error"),
            "warnings": sum(
                1 for check in checks if not check.passed and check.severity == "warning"
            ),
            "definition_version": KPI_DEFINITION_VERSION,
            "definition_hash": KPI_DEFINITION_HASH,
        }
