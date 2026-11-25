"""Metric-integrity tests for the Phase 05 acceptance criteria.

These cover the three properties that decide whether Claro is an analysis
platform or a dashboard:

1. Metric credibility - a rate is either computable from a large enough
   denominator or explicitly unavailable; per-policy denominators are that
   policy's own, never a scope-wide constant.
2. Strategy science - hit count alone never represents governance quality;
   detection quality, false-positive risk, false-negative risk and manual
   review load are all available per policy.
3. Replay isolation - the replay pool includes clean messages so a
   false-positive rate can exist at all.
"""

from __future__ import annotations

from claro.analytics.definitions import (
    KPI_FORMULAS,
    MIN_POLICY_DECISIONS,
    MIN_RATE_DENOMINATOR,
)
from claro.analytics.metrics import (
    classification_metrics,
    gated_rate,
    policy_effectiveness,
    predicted_positive,
    truth_positive,
)


def test_gated_rate_refuses_to_publish_a_ratio_from_too_few_observations() -> None:
    # Two observations cannot support a rate: the result must be unavailable
    # while still exposing the real sample size.
    result = gated_rate(1, 2, threshold=MIN_RATE_DENOMINATOR, label="自动处置率")
    assert result["value"] is None
    assert result["low_sample"] is True
    assert result["sample_size"] == 2
    assert result["numerator"] == 1
    assert result["denominator"] == 2
    assert "2" in result["reason"]

    # A zero denominator is also unavailable, never 0.
    empty = gated_rate(0, 0, threshold=MIN_RATE_DENOMINATOR, label="自动处置率")
    assert empty["value"] is None
    assert empty["denominator"] == 0


def test_gated_rate_publishes_a_value_once_the_denominator_is_sufficient() -> None:
    result = gated_rate(15, 30, threshold=MIN_RATE_DENOMINATOR, label="自动处置率")
    assert result["value"] == 0.5
    assert result["low_sample"] is False
    assert result["sample_size"] == 30
    assert result["reason"] is None


def test_policy_effectiveness_separates_quality_from_hit_count() -> None:
    """A heavily-hit policy that misfires must not look like a good policy."""
    quality = {
        "hit_messages": 400,
        "true_positives": 20,
        "false_positives": 180,
        "review_true_positives": 0,
        "review_false_positives": 0,
        "truth_positives": 400,
        "truth_negatives": 600,
    }
    result = policy_effectiveness(quality, min_samples=MIN_POLICY_DECISIONS)
    # 400 hits, but only 20 of them were correct.
    assert result["hit_messages"] == 400
    assert result["precision"] == 0.1
    assert result["false_positive_rate"] == 0.3
    assert result["false_negative_rate"] == 0.95
    assert result["low_sample"] is False

    # A precise policy with fewer hits scores strictly better on quality even
    # though it fires less often: hit count is not the objective.
    precise = policy_effectiveness(
        {
            "hit_messages": 50,
            "true_positives": 45,
            "false_positives": 5,
            "review_true_positives": 0,
            "review_false_positives": 0,
            "truth_positives": 400,
            "truth_negatives": 600,
        },
        min_samples=MIN_POLICY_DECISIONS,
    )
    assert precise["hit_messages"] < result["hit_messages"]
    assert precise["precision"] > result["precision"]
    assert precise["false_negative_rate"] < result["false_negative_rate"]


def test_policy_effectiveness_counts_review_hits_as_detections() -> None:
    """Routing a risky message to a moderator is a detection, not a miss."""
    quality = {
        "hit_messages": 40,
        "true_positives": 20,
        "false_positives": 5,
        "review_true_positives": 10,
        "review_false_positives": 5,
        "truth_positives": 40,
        "truth_negatives": 60,
    }
    result = policy_effectiveness(quality, min_samples=MIN_POLICY_DECISIONS)
    assert result["detected_true_positives"] == 30
    assert result["detected_false_positives"] == 10
    assert result["precision"] == 0.75
    assert result["recall"] == 0.75
    assert result["false_positive_rate"] == 0.166667
    assert result["false_negative_rate"] == 0.25
    # Review load is reported on its own axis.
    assert result["manual_review_rate"] == 0.375


def test_policy_effectiveness_flags_small_samples() -> None:
    result = policy_effectiveness(
        {
            "hit_messages": 5,
            "true_positives": 3,
            "false_positives": 1,
            "review_true_positives": 1,
            "review_false_positives": 0,
            "truth_positives": 10,
            "truth_negatives": 20,
        },
        min_samples=MIN_POLICY_DECISIONS,
    )
    assert result["low_sample"] is True
    assert result["min_samples"] == MIN_POLICY_DECISIONS


def test_replay_binary_semantics_produce_true_negatives() -> None:
    """Clean messages that are allowed must count as true negatives."""
    pairs = [
        (True, True),  # risky and acted on
        (False, True),  # clean but acted on -> false positive
        (False, False),  # clean and allowed -> true negative
        (True, False),  # risky and allowed -> false negative
    ]
    matrix = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for truth, predicted in pairs:
        if truth and predicted:
            matrix["tp"] += 1
        elif not truth and predicted:
            matrix["fp"] += 1
        elif truth and not predicted:
            matrix["fn"] += 1
        else:
            matrix["tn"] += 1
    metrics = classification_metrics(matrix)
    assert metrics["true_negatives"] == 1
    assert metrics["false_positive_rate"] == 0.5
    assert metrics["false_negative_rate"] == 0.5
    # An allow decision is a negative prediction.
    assert predicted_positive("allow") is False
    # A review decision consumes moderator capacity, so it counts as positive.
    assert predicted_positive("review") is True
    # Boundary is deliberately negative.
    assert truth_positive("boundary") is False


def test_kpi_formulas_cover_the_strategy_quality_dimensions() -> None:
    """The canonical formula set must expose the quality axes explicitly."""
    for key in (
        "policy_hit_rate",
        "policy_automatic_action_rate",
        "policy_precision",
        "policy_recall",
        "policy_manual_review_rate",
        "replay_sample_pool",
    ):
        assert key in KPI_FORMULAS
    assert "clean messages included" in KPI_FORMULAS["replay_sample_pool"]
