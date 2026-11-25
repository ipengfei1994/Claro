"""Service-layer aggregation tests with a hand-built fake repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from claro.analytics.filters import AnalyticsFilters
from claro.analytics.services import AnalyticsService


class FakeRepository:
    """Minimal in-memory repository with hand-checkable aggregates."""

    def overview(self, filters: AnalyticsFilters) -> dict[str, Any]:
        return {
            "total_messages": 10,
            "risk_messages": 2,
            "high_risk_messages": 1,
            "active_players": 3,
            "active_servers": 2,
            "unique_risk_players": 2,
            "repeat_offenders": 1,
            "first_message_at": datetime(2026, 1, 1, tzinfo=UTC),
            "last_message_at": datetime(2026, 1, 2, tzinfo=UTC),
        }

    def governance_totals(self, filters: AnalyticsFilters) -> dict[str, Any]:
        return {
            "total_decisions": 10,
            "decided_messages": 10,
            "eligible_finalized": 2,
            "auto_decided": 1,
            "review_decisions": 1,
            "human_reviewed": 1,
            "overridden": 0,
            "requires_review": 1,
            "linked_evaluations": 1,
        }

    def time_series(self, filters: AnalyticsFilters, grain: str) -> list[dict[str, Any]]:
        return [
            {
                "bucket": datetime(2026, 1, 1, tzinfo=UTC),
                "total_messages": 10,
                "risk_messages": 2,
                "high_risk_messages": 1,
            }
        ]

    def category_distribution(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return [{"category": "spam", "message_count": 2, "event_count": 2, "avg_score": 0.7}]

    def severity_distribution(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return [{"severity": "high", "message_count": 1}]

    def cooccurrence(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return []

    def server_ranking(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return [
            {
                "server_ref": "s1",
                "server_name": "Server 1",
                "region": "apac",
                "total_messages": 100,
                "risk_messages": 20,
                "high_risk_messages": 10,
                "active_players": 30,
                "risk_players": 20,
                "total_decisions": 4,
                "auto_decided": 2,
                "review_decisions": 1,
                "status_decisions": 2,
            },
            {
                "server_ref": "s2",
                "server_name": "Server 2",
                "region": "apac",
                "total_messages": 5,
                "risk_messages": 0,
                "high_risk_messages": 0,
                "active_players": 2,
                "risk_players": 0,
                "total_decisions": 0,
                "auto_decided": 0,
                "review_decisions": 0,
                "status_decisions": 0,
            },
        ]

    def alliance_ranking(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return [
            {
                "alliance_ref": "a1",
                "alliance_name": "Alliance 1",
                "server_ref": "s1",
                "total_messages": 100,
                "risk_messages": 20,
                "high_risk_messages": 10,
                "active_players": 30,
                "high_risk_players": 10,
                "total_decisions": 2,
                "auto_decided": 1,
            }
        ]

    def player_profiles(self, filters: AnalyticsFilters, limit: int) -> list[dict[str, Any]]:
        return [
            {
                "sender_ref": "p1",
                "player_id": "00000000-0000-0000-0000-000000000001",
                "total_messages": 100,
                "risk_messages": 20,
                "last_risk_at": datetime(2026, 1, 1, tzinfo=UTC),
                "decision_count": 3,
                "restrictive_count": 1,
                "sanction_count": 0,
            }
        ]

    def decision_distribution(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return [
            {
                "action": "allow",
                "decision_status": "auto_decided",
                "decision_count": 8,
                "message_count": 8,
            }
        ]

    def moderation_totals(self, filters: AnalyticsFilters) -> dict[str, Any]:
        return {
            "total_tasks": 4,
            "completed_tasks": 2,
            "pending_tasks": 2,
            "second_review_tasks": 1,
            "linked_decisions": 1,
            "valid_durations": 2,
            "avg_seconds": 100,
            "p50_seconds": 100,
            "p90_seconds": 180,
            "review_count": 0,
            "override_count": 0,
        }

    def moderation_by_status(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return [{"status": "resolved", "resolution": "approved", "task_count": 2, "completed": 2}]

    def enforcement_distribution(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return [
            {
                "action_type": "message_block",
                "status": "executed",
                "simulated": True,
                "action_count": 2,
                "target_count": 2,
                "avg_duration_seconds": None,
                "with_expiry": 0,
                "released_count": 0,
            }
        ]

    def observed_risk_vs_label(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return [
            {"truth_label": "risk", "risk_level": "high"},
            {"truth_label": "normal", "risk_level": "normal"},
        ]

    def model_runs(self, model_id: str | None) -> list[dict[str, Any]]:
        return [
            {
                "run_id": "00000000-0000-0000-0000-000000000010",
                "model_id": "model-v1",
                "model_name": "risk-model",
                "model_version": 1,
                "algorithm": "logistic_regression",
                "dataset_name": "synthetic",
                "split": "test",
                "message_count": 100,
                "metrics": {"binary": {"f1": 0.9}},
                "per_label": {"spam": {"precision": 1, "recall": 1, "f1": 1, "support": 10}},
                "case_counts": {},
                "leakage": {},
                "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            }
        ]

    def model_error_cases(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return [
            {
                "error_type": "borderline",
                "category": "spam",
                "truth_label": "risk",
                "case_count": 3,
                "avg_predicted_score": 0.6,
            }
        ]

    def policy_hits(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return [
            {
                "policy_key": "p1",
                "policy_id": "00000000-0000-0000-0000-000000000020",
                "current_version": 1,
                "configured_action": "review",
                "cumulative_hit_count": 5,
                "replay_hit_messages": 40,
                "automatic_hit_messages": 25,
                "review_hit_messages": 15,
                "enforcement_hit_messages": 25,
                "evaluated_messages": 100,
                "review_suggestions": 15,
                "restrictive_suggestions": 25,
            }
        ]

    def policy_quality(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return [
            {
                "policy_key": "p1",
                "hit_messages": 40,
                "true_positives": 20,
                "false_positives": 5,
                "review_true_positives": 10,
                "review_false_positives": 5,
                "truth_negatives": 60,
                "truth_positives": 40,
            }
        ]

    def detection_quality(self, filters: AnalyticsFilters) -> dict[str, Any]:
        return {
            "true_positives": 8,
            "false_positives": 2,
            "false_negatives": 0,
            "true_negatives": 90,
            "sample_size": 100,
        }

    def policy_evaluation_actions(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return [
            {
                "suggested_action": "review",
                "message_count": 4,
                "evaluation_count": 4,
                "overridden": 0,
            }
        ]

    def quality_orphans(self) -> dict[str, Any]:
        return {
            "risk_event_orphans": 0,
            "decision_orphans": 0,
            "enforcement_orphans": 0,
        }

    def quality_duplicates(self) -> dict[str, Any]:
        return {
            "duplicate_message_ids": 0,
            "duplicate_external_ids": 0,
            "duplicate_risk_events": 0,
        }

    def quality_coverage(self) -> dict[str, Any]:
        return {
            "messages": 10,
            "risk_result_messages": 2,
            "linked_decisions": 2,
            "decisions": 10,
            "linked_cases": 1,
            "cases": 4,
            "reviews": 0,
            "feedback": 0,
        }

    def quality_time(self) -> dict[str, Any]:
        return {
            "invalid_message_time": 0,
            "invalid_case_time": 0,
            "ingest_lag_p95_seconds": 1.5,
        }


def _filters() -> AnalyticsFilters:
    return AnalyticsFilters(
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 2, 1, tzinfo=UTC),
    )


def test_overview_uses_canonical_risk_rate_and_reports_detection_quality() -> None:
    result = AnalyticsService(FakeRepository()).overview(_filters())
    assert result["kpis"]["total_messages"] == 10
    assert result["kpis"]["risk_rate"]["risk_rate"] == 0.2
    # Detection quality is measured against the synthetic ground truth.
    assert result["kpis"]["detection_precision"] == 0.8
    assert result["kpis"]["detection_recall"] == 1.0
    assert result["kpis"]["detection_sample_size"] == 100
    # The governance denominator here is 2, below the gate of 30, so the ratio
    # must be reported as unavailable instead of a misleading 0.5.
    assert result["kpis"]["automatic_handling_rate"] is None
    assert result["kpis"]["automatic_handling_rate_detail"]["low_sample"] is True
    assert result["kpis"]["automatic_handling_rate_detail"]["sample_size"] == 2


def test_risk_service_reports_category_share_and_anomalies() -> None:
    result = AnalyticsService(FakeRepository()).risk(_filters(), "day")
    assert result["series"][0]["risk_rate"] == 0.2
    assert result["categories"][0]["share"] == 1.0
    assert result["cooccurrence"] == []
    assert result["anomaly_bucket_indices"] == []


def test_community_service_flags_low_sample_units() -> None:
    result = AnalyticsService(FakeRepository()).community(_filters())
    assert result["servers"][0]["risk_rate"] == 0.2
    assert result["servers"][0]["low_sample"] is False
    assert result["servers"][1]["low_sample"] is True
    assert abs(result["alliances"][0]["high_risk_player_share"] - 1 / 3) < 1e-6
    assert result["players"][0]["risk_rate"] == 0.2


def test_governance_service_keeps_moderation_and_feedback_limits_explicit() -> None:
    result = AnalyticsService(FakeRepository()).governance(_filters())
    # Governance ratios are gated: with 2 eligible decisions the ratio is
    # unavailable, not 0.5.
    assert result["decisions"]["automatic_handling_rate"] is None
    assert result["decisions"]["automatic_handling_rate_detail"]["low_sample"] is True
    assert result["decisions"]["override_rate"] is None
    assert result["moderation"]["p50_seconds"] == 100
    assert result["moderation"]["human_review_duration_available"] is False
    assert result["observed_confusion"]["samples"] == 2
    # The persisted risk_result slice is too small to interpret.
    assert result["observed_confusion"]["low_sample"] is True
    assert result["observed_confusion"]["interpretable"] is False
    # The detection layer has a full-window baseline.
    assert result["detection_confusion"]["samples"] == 100
    assert result["detection_confusion"]["precision"] == 0.8


def test_model_and_strategy_services_expose_limited_comparisons() -> None:
    service = AnalyticsService(FakeRepository())
    model = service.model(_filters())
    assert model["per_category"][0]["support"] == 10
    assert model["version_comparison_available"] is False
    assert model["model_human_agreement"]["available"] is False
    strategy = service.strategy(_filters())
    policy = strategy["policies"][0]
    # Per-policy rates use that policy's own denominator, not a scope-wide
    # constant broadcast onto every row.
    assert policy["hit_rate"]["value"] == 0.4
    assert policy["hit_rate"]["denominator"] == 100
    assert policy["automatic_action_rate"]["value"] == 0.625
    assert policy["automatic_action_rate"]["denominator"] == 40
    assert policy["manual_review_rate"]["value"] == 0.375
    # Quality is scored per policy against the ground truth. Review hits count
    # as detections: tp=20+10=30, fp=5+5=10, fn=40-30=10, tn=60-10=50.
    assert policy["precision"] == 0.75
    assert policy["recall"] == 0.75
    assert policy["false_positive_rate"] == 0.166667
    assert policy["false_negative_rate"] == 0.25
    assert policy["quality_sample_size"] == 40
    assert policy["quality_low_sample"] is False
    assert strategy["version_comparison"]["available"] is False
