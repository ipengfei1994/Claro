"""Canonical KPI identifiers, data-source tiers and analysis constants.

The single human-readable definition lives in docs/KPI_DEFINITIONS.md. This
module provides the machine-readable identifiers that quality checks compare
against, so a page cannot silently use a different formula.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum

# Must be bumped together with docs/KPI_DEFINITIONS.md whenever a formula changes.
KPI_DEFINITION_VERSION = "phase-05.1"

# Canonical formula identifiers. Quality checks compare this hash with the
# version returned by the service layer to detect divergent implementations.
KPI_FORMULAS: dict[str, str] = {
    "total_messages": "count_distinct(message.id) within scoped message window",
    "risk_messages": "count_distinct(risk_event.message_id) joined to scoped messages",
    "risk_rate": "risk_messages / total_messages",
    "high_risk_messages": "count_distinct(message.id) with risk_event severity in high,critical",
    "unique_risk_players": "count_distinct(message.player_id) among risk messages",
    "repeat_offenders": "players with risk_message_count >= repeat_threshold in window",
    "automatic_handling_rate": "auto_decided / (auto_decided + human_reviewed + overridden)",
    "decision_override_rate": "overridden / (human_reviewed + overridden)",
    "task_completion_duration": "moderation_case.closed_at - moderation_case.opened_at",
    "model_metrics": "read evaluation_run.metrics and per_label; no recomputation",
    "policy_hit_rate": "hit_messages / messages_with_policy_evaluation",
    "replay_precision": "tp / (tp + fp); positive = label risk and action != allow",
    "replay_recall": "tp / (tp + fn); boundary label counted as negative",
}
KPI_DEFINITION_HASH = hashlib.sha256(
    json.dumps(KPI_FORMULAS, sort_keys=True, ensure_ascii=False).encode("utf-8")
).hexdigest()

PRIMARY_DATASET_NAME = "phase-02-synthetic-s20261125-p5000-m50000"
LOW_SAMPLE_MESSAGES = 30
MIN_REPLAY_SAMPLES = 100

HIGH_SEVERITIES = ("high", "critical")
RESTRICTIVE_ACTIONS = (
    "warn",
    "flag",
    "review",
    "mute",
    "block",
    "temp_ban",
    "perm_ban",
    "restrict",
)
FINALIZED_DECISION_STATUSES = ("auto_decided", "human_reviewed", "overridden")
REVIEW_DECISION_STATUSES = ("pending_review", "human_reviewed", "overridden")
PENDING_CASE_STATUSES = ("open", "pending", "in_review", "second_review", "escalated")


class DataSourceTier(StrEnum):
    OBSERVED = "observed"
    SYNTHETIC_SNAPSHOT = "synthetic_snapshot"
    DERIVED = "derived"


TIER_LABELS: dict[str, str] = {
    DataSourceTier.OBSERVED: "实际观测记录",
    DataSourceTier.SYNTHETIC_SNAPSHOT: "合成快照 · 非线上数据",
    DataSourceTier.DERIVED: "统一口径计算",
}
