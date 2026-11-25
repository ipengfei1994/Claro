"""Analytics services used by the CLI, reports and Streamlit pages.

Services interpret repository rows using the canonical formulas in
``claro.analytics.metrics`` and ``docs/KPI_DEFINITIONS.md``. They return plain
dictionaries so that every consumer sees the same numbers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from claro.analytics import sql_queries as q
from claro.analytics.data_access import AnalyticsRepository
from claro.analytics.definitions import (
    KPI_DEFINITION_HASH,
    KPI_DEFINITION_VERSION,
    LOW_SAMPLE_MESSAGES,
    TIER_LABELS,
    DataSourceTier,
)
from claro.analytics.filters import AnalyticsFilters
from claro.analytics.metrics import (
    anomaly_peaks,
    as_float,
    as_int,
    binary_confusion,
    classification_metrics,
    low_sample,
    predicted_positive,
    ratio,
    risk_rate,
    truth_positive,
)
from claro.analytics.quality import DataQualityService


def jsonable(value: Any) -> Any:
    """Convert database scalars into JSON-safe values for UI and reports."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


class AnalyticsService:
    """Facade exposing risk, community, governance and model analytics."""

    def __init__(self, repository: AnalyticsRepository) -> None:
        self._repository = repository
        self._quality = DataQualityService(repository)

    @property
    def definition(self) -> dict[str, str]:
        return {
            "version": KPI_DEFINITION_VERSION,
            "hash": KPI_DEFINITION_HASH,
        }

    def _envelope(self, filters: AnalyticsFilters, tier: DataSourceTier) -> dict[str, Any]:
        return {
            "definition": self.definition,
            "data_source_tier": tier.value,
            "data_source_label": TIER_LABELS[tier],
            "filters": filters.summary(),
            "generated_at": datetime.now(UTC).isoformat(),
            "synthetic_notice": "所有数据均为 Synthetic Data，不代表真实线上运营。",
        }

    def datasets(self) -> list[dict[str, Any]]:
        return [jsonable(row) for row in self._repository.datasets()]

    def quality(self) -> dict[str, Any]:
        return jsonable(self._quality.summary())

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------
    def overview(self, filters: AnalyticsFilters) -> dict[str, Any]:
        raw = self._repository.overview(filters)
        governance = self._repository.governance_totals(filters)
        quality = self._quality.summary()
        result = self._envelope(filters, DataSourceTier.SYNTHETIC_SNAPSHOT)
        result.update(
            {
                "kpis": {
                    "total_messages": as_int(raw["total_messages"]),
                    "risk_messages": as_int(raw["risk_messages"]),
                    "risk_rate": risk_rate(raw["total_messages"], raw["risk_messages"]),
                    "high_risk_messages": as_int(raw["high_risk_messages"]),
                    "high_risk_rate": risk_rate(raw["total_messages"], raw["high_risk_messages"]),
                    "unique_risk_players": as_int(raw["unique_risk_players"]),
                    "repeat_offenders": as_int(raw["repeat_offenders"]),
                    "governance_decisions": as_int(governance["total_decisions"]),
                    "eligible_finalized_decisions": as_int(governance["eligible_finalized"]),
                    "automatic_handling_rate": ratio(
                        governance["auto_decided"], governance["eligible_finalized"]
                    ),
                    "review_rate": ratio(
                        governance["review_decisions"], governance["eligible_finalized"]
                    ),
                    "false_positive_rate": None,
                    "false_negative_rate": None,
                },
                "coverage": {
                    "active_players": as_int(raw["active_players"]),
                    "active_servers": as_int(raw["active_servers"]),
                    "first_message_at": jsonable(raw["first_message_at"]),
                    "last_message_at": jsonable(raw["last_message_at"]),
                },
                "quality": {
                    "passed": quality["passed"],
                    "failed": quality["failed"],
                    "errors": quality["errors"],
                    "warnings": quality["warnings"],
                },
                "notes": [
                    "Risk Rate = 去重风险消息数 / 去重消息数，时间轴统一使用 message.occurred_at。",
                    "Automatic Handling Rate 分母仅为有决策状态的记录，"
                    "当前样本量见 eligible_finalized_decisions。",
                    "误杀率/漏判率需要人工标签；当前 governance_feedback 为 0，显示不可计算。",
                ],
            }
        )
        return jsonable(result)

    # ------------------------------------------------------------------
    # Risk analytics
    # ------------------------------------------------------------------
    def risk(self, filters: AnalyticsFilters, grain: q.Grain = "day") -> dict[str, Any]:
        series_rows = self._repository.time_series(filters, grain)
        series: list[dict[str, Any]] = []
        for row in series_rows:
            entry = {
                "bucket": jsonable(row["bucket"]),
                "total_messages": as_int(row["total_messages"]),
                "risk_messages": as_int(row["risk_messages"]),
                "high_risk_messages": as_int(row["high_risk_messages"]),
                "risk_rate": ratio(row["risk_messages"], row["total_messages"]),
            }
            series.append(entry)
        peaks = anomaly_peaks(
            [float(item["risk_rate"] or 0.0) for item in series], sigma=3.0
        )
        categories = []
        risk_total = as_int(self._repository.overview(filters)["risk_messages"])
        for row in self._repository.category_distribution(filters):
            count = as_int(row["message_count"])
            categories.append(
                {
                    "category": row["category"],
                    "message_count": count,
                    "event_count": as_int(row["event_count"]),
                    "share": ratio(count, risk_total),
                    "avg_score": as_float(row["avg_score"]),
                }
            )
        severities = [
            {"severity": row["severity"], "message_count": as_int(row["message_count"])}
            for row in self._repository.severity_distribution(filters)
        ]
        cooccurrence = [
            {
                "category_a": row["category_a"],
                "category_b": row["category_b"],
                "message_count": as_int(row["message_count"]),
            }
            for row in self._repository.cooccurrence(filters)
        ]
        result = self._envelope(filters, DataSourceTier.DERIVED)
        result.update(
            {
                "grain": grain,
                "series": series,
                "categories": categories,
                "severities": severities,
                "cooccurrence": cooccurrence,
                "anomaly_bucket_indices": peaks,
                "notes": [
                    "类别分布按 (message_id, category) 去重，"
                    "多标签消息的类别占比之和可能超过 100%。",
                    "共现矩阵为空表示当前合成数据集中没有消息携带两个及以上风险类别。",
                    "异常峰值为 mean + 3σ 的统计识别结果，不推断因果。",
                ],
            }
        )
        return jsonable(result)

    # ------------------------------------------------------------------
    # Community analytics
    # ------------------------------------------------------------------
    def community(self, filters: AnalyticsFilters, *, limit: int = 100) -> dict[str, Any]:
        servers: list[dict[str, Any]] = []
        for row in self._repository.server_ranking(filters):
            total = as_int(row["total_messages"])
            risk = as_int(row["risk_messages"])
            servers.append(
                {
                    "server_ref": row["server_ref"],
                    "server_name": row["server_name"],
                    "region": row["region"],
                    "total_messages": total,
                    "risk_messages": risk,
                    "risk_rate": ratio(risk, total),
                    "high_risk_messages": as_int(row["high_risk_messages"]),
                    "active_players": as_int(row["active_players"]),
                    "risk_players": as_int(row["risk_players"]),
                    "total_decisions": as_int(row["total_decisions"]),
                    "automatic_decisions": as_int(row["auto_decided"]),
                    "review_decisions": as_int(row["review_decisions"]),
                    "automatic_handling_rate": ratio(
                        row["auto_decided"], row["status_decisions"]
                    ),
                    "low_sample": low_sample(total, LOW_SAMPLE_MESSAGES),
                }
            )
        alliances: list[dict[str, Any]] = []
        for row in self._repository.alliance_ranking(filters):
            total = as_int(row["total_messages"])
            risk = as_int(row["risk_messages"])
            alliances.append(
                {
                    "alliance_ref": row["alliance_ref"],
                    "alliance_name": row["alliance_name"],
                    "server_ref": row["server_ref"],
                    "total_messages": total,
                    "risk_messages": risk,
                    "risk_rate": ratio(risk, total),
                    "high_risk_messages": as_int(row["high_risk_messages"]),
                    "active_players": as_int(row["active_players"]),
                    "high_risk_players": as_int(row["high_risk_players"]),
                    "high_risk_player_share": ratio(
                        row["high_risk_players"], row["active_players"]
                    ),
                    "total_decisions": as_int(row["total_decisions"]),
                    "low_sample": low_sample(total, LOW_SAMPLE_MESSAGES),
                }
            )
        players: list[dict[str, Any]] = []
        for row in self._repository.player_profiles(filters, limit=limit):
            total = as_int(row["total_messages"])
            risk = as_int(row["risk_messages"])
            players.append(
                {
                    "player_ref": row["sender_ref"],
                    "player_id": row["player_id"],
                    "total_messages": total,
                    "risk_messages": risk,
                    "risk_rate": ratio(risk, total),
                    "last_risk_at": jsonable(row["last_risk_at"]),
                    "decision_count": as_int(row["decision_count"]),
                    "restrictive_decisions": as_int(row["restrictive_count"]),
                    "simulated_sanctions": as_int(row["sanction_count"]),
                    "low_sample": low_sample(total, LOW_SAMPLE_MESSAGES),
                }
            )
        result = self._envelope(filters, DataSourceTier.DERIVED)
        result.update(
            {
                "servers": servers,
                "alliances": alliances,
                "players": players,
                "notes": [
                    "风险数量与风险率必须同时解读；消息量大的单位风险数天然更高。",
                    "消息数低于 30 的服务器/联盟/玩家标记为低样本量。",
                    "玩家画像仅用于分析与模拟治理；risk_propensity 是生成参数，不是违规概率。",
                ],
            }
        )
        return jsonable(result)

    # ------------------------------------------------------------------
    # Governance analytics
    # ------------------------------------------------------------------
    def governance(self, filters: AnalyticsFilters) -> dict[str, Any]:
        totals = self._repository.governance_totals(filters)
        eligible = as_int(totals["eligible_finalized"])
        auto = as_int(totals["auto_decided"])
        reviewed = as_int(totals["human_reviewed"])
        overridden = as_int(totals["overridden"])
        decisions = {
            "total_decisions": as_int(totals["total_decisions"]),
            "decided_messages": as_int(totals["decided_messages"]),
            "eligible_finalized": eligible,
            "automatic_decisions": auto,
            "manual_review_decisions": as_int(totals["review_decisions"]),
            "automatic_handling_rate": ratio(auto, eligible),
            "review_rate": ratio(as_int(totals["review_decisions"]), eligible),
            "override_rate": ratio(overridden, reviewed + overridden),
            "linked_evaluations": as_int(totals["linked_evaluations"]),
        }
        distribution = [
            {
                "action": row["action"],
                "decision_status": row["decision_status"],
                "decision_count": as_int(row["decision_count"]),
                "message_count": as_int(row["message_count"]),
                "share": ratio(row["decision_count"], decisions["total_decisions"]),
            }
            for row in self._repository.decision_distribution(filters)
        ]
        moderation_raw = self._repository.moderation_totals(filters)
        # Exact P50/P90 are computed by PostgreSQL percentile_cont in the query.
        moderation = {
            "total_tasks": as_int(moderation_raw["total_tasks"]),
            "completed_tasks": as_int(moderation_raw["completed_tasks"]),
            "pending_tasks": as_int(moderation_raw["pending_tasks"]),
            "second_review_tasks": as_int(moderation_raw["second_review_tasks"]),
            "linked_decisions": as_int(moderation_raw["linked_decisions"]),
            "valid_durations": as_int(moderation_raw["valid_durations"]),
            "avg_seconds": as_float(moderation_raw["avg_seconds"]),
            "p50_seconds": as_float(moderation_raw["p50_seconds"]),
            "p90_seconds": as_float(moderation_raw["p90_seconds"]),
            "review_count": as_int(moderation_raw["review_count"]),
            "override_count": as_int(moderation_raw["override_count"]),
            "task_completion_rate": ratio(
                moderation_raw["completed_tasks"], moderation_raw["total_tasks"]
            ),
            "second_review_rate": ratio(
                moderation_raw["second_review_tasks"], moderation_raw["completed_tasks"]
            ),
            "human_review_duration_available": as_int(moderation_raw["review_count"]) > 0,
        }
        moderation_status = [
            {
                "status": row["status"],
                "resolution": row["resolution"],
                "task_count": as_int(row["task_count"]),
                "completed": as_int(row["completed"]),
            }
            for row in self._repository.moderation_by_status(filters)
        ]
        enforcement = [
            {
                "action_type": row["action_type"],
                "status": row["status"],
                "simulated": bool(row["simulated"]),
                "action_count": as_int(row["action_count"]),
                "target_count": as_int(row["target_count"]),
                "avg_duration_seconds": as_float(row["avg_duration_seconds"]),
                "with_expiry": as_int(row["with_expiry"]),
                "released_count": as_int(row["released_count"]),
            }
            for row in self._repository.enforcement_distribution(filters)
        ]
        observed = self._repository.observed_risk_vs_label(filters)
        pairs = [
            (truth_positive(row["truth_label"]), predicted_positive(row["risk_level"]))
            for row in observed
            if row["truth_label"] is not None
        ]
        observed_confusion = classification_metrics(binary_confusion(pairs))
        result = self._envelope(filters, DataSourceTier.DERIVED)
        result.update(
            {
                "decisions": decisions,
                "decision_distribution": distribution,
                "moderation": moderation,
                "moderation_by_status": moderation_status,
                "enforcement": enforcement,
                "observed_confusion": observed_confusion,
                "notes": [
                    "Automatic Handling Rate 分母 = 有决策状态且非 cancelled 的记录；"
                    "其余为生成器 legacy 记录。",
                    "审核耗时来自 moderation_case.opened_at → closed_at，"
                    "属于合成任务关闭耗时，不是人工审核耗时。",
                    "moderation_review 与 governance_feedback 均为 0 行，"
                    "人工推翻率与线上误杀/漏判不可计算。",
                    "所有 enforcement_action 均为 simulated=true 的模拟处置。",
                ],
            }
        )
        return jsonable(result)

    # ------------------------------------------------------------------
    # Model analytics
    # ------------------------------------------------------------------
    def model(self, filters: AnalyticsFilters) -> dict[str, Any]:
        runs = []
        for row in self._repository.model_runs(filters.model_id):
            runs.append(
                {
                    "run_id": str(row["run_id"]),
                    "model_id": row["model_id"],
                    "model_name": row["model_name"],
                    "model_version": as_int(row["model_version"]),
                    "algorithm": row["algorithm"],
                    "dataset_name": row["dataset_name"],
                    "split": row["split"],
                    "message_count": as_int(row["message_count"]),
                    "metrics": jsonable(row["metrics"]),
                    "per_label": jsonable(row["per_label"]),
                    "case_counts": jsonable(row["case_counts"]),
                    "leakage": jsonable(row["leakage"]),
                    "created_at": jsonable(row["created_at"]),
                }
            )
        per_category: list[dict[str, Any]] = []
        if runs:
            for label, values in sorted(runs[0]["per_label"].items()):
                per_category.append(
                    {
                        "category": label,
                        "precision": values.get("precision"),
                        "recall": values.get("recall"),
                        "f1": values.get("f1"),
                        "support": as_int(values.get("support")),
                        "confusion_matrix": values.get("confusion_matrix"),
                    }
                )
        error_cases = [
            {
                "error_type": row["error_type"],
                "category": row["category"],
                "truth_label": row["truth_label"],
                "case_count": as_int(row["case_count"]),
                "avg_predicted_score": as_float(row["avg_predicted_score"]),
            }
            for row in self._repository.model_error_cases(filters)
        ]
        observed = self._repository.observed_risk_vs_label(filters)
        pairs = [
            (truth_positive(row["truth_label"]), predicted_positive(row["risk_level"]))
            for row in observed
            if row["truth_label"] is not None
        ]
        confusion = classification_metrics(binary_confusion(pairs))
        comparable = len({(run["dataset_name"], run["split"]) for run in runs}) == 1
        result = self._envelope(filters, DataSourceTier.OBSERVED)
        result.update(
            {
                "runs": runs,
                "per_category": per_category,
                "error_cases": error_cases,
                "observed_confusion": confusion,
                "version_comparison_available": len(runs) > 1 and comparable,
                "version_comparison_note": (
                    "仅当运行数量大于 1 且 dataset/split 完全一致时才可比较。"
                    if not comparable or len(runs) <= 1
                    else "数据集与 split 一致，可并列展示指标。"
                ),
                "model_human_agreement": {
                    "available": False,
                    "reason": "moderation_review 为 0 行，缺少人工标签；不能称为严格准确率。",
                },
                "notes": [
                    "指标来自 evaluation_run 的持久化结果，不在展示层重新计算。",
                    "标签为合成 ground truth，不代表真实线上准确率。",
                    "observed_confusion 仅覆盖 risk_result 已落库的消息，样本量见 samples。",
                ],
            }
        )
        return jsonable(result)

    # ------------------------------------------------------------------
    # Strategy evaluation (historical, before replay)
    # ------------------------------------------------------------------
    def strategy(self, filters: AnalyticsFilters) -> dict[str, Any]:
        hits = self._repository.policy_hits(filters)
        actions = self._repository.policy_evaluation_actions(filters)
        policies = [
            {
                "policy_key": row["policy_key"],
                "policy_id": str(row["policy_id"]),
                "version": as_int(row["current_version"]),
                "configured_action": row["configured_action"],
                "cumulative_hit_count": as_int(row["cumulative_hit_count"]),
                "replay_hit_messages": as_int(row["replay_hit_messages"]),
                "evaluated_messages": as_int(row["evaluated_messages"]),
                "hit_rate": ratio(row["replay_hit_messages"], row["evaluated_messages"]),
                "review_suggestions": as_int(row["review_suggestions"]),
                "automatic_action_rate": ratio(
                    as_int(row["evaluated_messages"]) - as_int(row["review_suggestions"]),
                    as_int(row["evaluated_messages"]),
                ),
                "false_positive_rate": None,
                "false_negative_rate": None,
                "precision": None,
                "recall": None,
                "f1": None,
            }
            for row in hits
            if as_int(row["current_version"]) > 0
        ]
        action_rows = [
            {
                "suggested_action": row["suggested_action"],
                "message_count": as_int(row["message_count"]),
                "evaluation_count": as_int(row["evaluation_count"]),
                "overridden": as_int(row["overridden"]),
            }
            for row in actions
        ]
        result = self._envelope(filters, DataSourceTier.DERIVED)
        result.update(
            {
                "policies": policies,
                "action_distribution": action_rows,
                "version_comparison": {
                    "available": False,
                    "reason": "当前所有策略仅有 v1，无历史版本；"
                    "请使用 Strategy Replay 的候选配置对比。",
                },
                "notes": [
                    "Policy Hit Rate = 命中消息数 / 有策略评估记录的消息数，不是策略准确率。",
                    "Precision/Recall/F1 需要标注数据；请使用回放评估页查看离线模拟指标。",
                    "命中计数为累计快照，无时间序列，不可直接解读为趋势。",
                ],
            }
        )
        return jsonable(result)
