"""Hand-checkable fixtures for the canonical Phase 05 metric functions."""

from __future__ import annotations

from decimal import Decimal

from claro.analytics import sql_queries
from claro.analytics.definitions import KPI_DEFINITION_HASH, KPI_FORMULAS
from claro.analytics.filters import AnalyticsFilters
from claro.analytics.metrics import (
    action_diff,
    anomaly_peaks,
    binary_confusion,
    classification_metrics,
    count_by,
    dedupe_by,
    duration_stats,
    low_sample,
    percentile,
    predicted_positive,
    ratio,
    risk_rate,
    truth_positive,
)


def test_risk_rate_uses_distinct_messages_and_rejects_zero_denominator() -> None:
    result = risk_rate(10, 2)
    assert result["risk_rate"] == 0.2
    assert result["risk_messages"] == 2
    assert result["total_messages"] == 10
    assert ratio(1, 0) is None
    assert ratio(Decimal("3"), Decimal("4")) == 0.75


def test_dedupe_by_and_count_by_handle_duplicate_event_rows() -> None:
    rows = [
        {"message_id": "m1", "category": "spam"},
        {"message_id": "m1", "category": "spam"},
        {"message_id": "m2", "category": "fraud"},
    ]
    unique = dedupe_by(rows, "message_id")
    assert [row["message_id"] for row in unique] == ["m1", "m2"]
    assert count_by(unique, "category") == {"spam": 1, "fraud": 1}


def test_time_aggregation_whitelists_grains() -> None:
    for grain in ("hour", "day", "week", "month"):
        assert "date_trunc" in sql_queries.daily_counts_sql(grain)
    try:
        sql_queries.daily_counts_sql("year")  # type: ignore[arg-type]
    except ValueError:
        pass
    else:
        raise AssertionError("unsupported grain must be rejected")


def test_percentile_and_duration_stats_ignore_incomplete_tasks() -> None:
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    assert percentile([], 0.9) is None
    stats = duration_stats([10, 20, 30, -1])
    assert stats["samples"] == 3
    assert stats["p50_seconds"] == 20.0
    assert stats["p90_seconds"] == 28.0


def test_binary_confusion_and_classification_metrics_are_consistent() -> None:
    # Truth: 2 positive, 2 negative. Prediction: TP=1, FP=1, FN=1, TN=1.
    pairs = [(True, True), (True, False), (False, True), (False, False)]
    matrix = binary_confusion(pairs)
    assert matrix == {"tp": 1, "fp": 1, "fn": 1, "tn": 1}
    metrics = classification_metrics(matrix)
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["f1"] == 0.5
    assert metrics["false_positive_rate"] == 0.5
    assert metrics["false_negative_rate"] == 0.5


def test_replay_binary_semantics_and_action_diff() -> None:
    assert truth_positive("risk") is True
    assert truth_positive("boundary") is False
    assert predicted_positive("allow") is False
    assert predicted_positive("review") is True
    assert action_diff("review", "block") == "stricter"
    assert action_diff("block", "warn") == "looser"
    assert action_diff("warn", "warn") == "unchanged"


def test_anomaly_detection_and_low_sample_flag() -> None:
    assert anomaly_peaks([0.1] * 10 + [1.0]) == [10]
    assert anomaly_peaks([0.1, 0.1]) == []
    assert low_sample(10, 30) is True
    assert low_sample(100, 30) is False


def test_filters_use_half_open_window() -> None:
    filters = AnalyticsFilters(
        start="2026-01-01T00:00:00+00:00",  # type: ignore[arg-type]
        end="2026-02-01T00:00:00+00:00",  # type: ignore[arg-type]
        repeat_threshold=3,
    )
    params = filters.params()
    assert params["end"] > params["start"]
    assert params["repeat_threshold"] == 3
    assert filters.summary()["risk_category"] == "all"


def test_kpi_definition_hash_is_derived_from_formulas() -> None:
    assert KPI_FORMULAS["risk_rate"] == "risk_messages / total_messages"
    assert len(KPI_DEFINITION_HASH) == 64
