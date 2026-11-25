from __future__ import annotations

import numpy as np

from claro.risk_engine.evaluation.metrics import (
    binary_f1,
    binary_metrics,
    multilabel_metrics,
)


def test_binary_metrics_report_confusion_and_error_rates() -> None:
    metrics = binary_metrics([1, 0, 1, 0], [1, 1, 0, 0])
    assert metrics["samples"] == 4
    assert metrics["accuracy"] == 0.5
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["f1"] == 0.5
    assert metrics["false_positive_rate"] == 0.5
    assert metrics["false_negative_rate"] == 0.5
    assert metrics["confusion_matrix"] == {"tn": 1, "fp": 1, "fn": 1, "tp": 1}
    assert metrics["false_positives"] == 1
    assert metrics["false_negatives"] == 1


def test_binary_metrics_handle_empty_input() -> None:
    assert binary_metrics([], []) == {"samples": 0}
    assert binary_f1([], []) == 0.0


def test_multilabel_metrics_are_computed_per_label() -> None:
    truth = np.array([[1, 0], [0, 1], [1, 1]])
    predicted = np.array([[1, 0], [1, 0], [0, 1]])
    metrics = multilabel_metrics(truth, predicted, ["spam", "harassment"])

    assert metrics["samples"] == 3
    assert metrics["labels"] == ["spam", "harassment"]
    for label in ("spam", "harassment"):
        assert set(metrics["per_label"][label]["confusion_matrix"]) == {"tn", "fp", "fn", "tp"}
    assert metrics["per_label"]["spam"]["confusion_matrix"] == {
        "tn": 0,
        "fp": 1,
        "fn": 1,
        "tp": 1,
    }
    assert metrics["per_label"]["harassment"]["confusion_matrix"] == {
        "tn": 1,
        "fp": 0,
        "fn": 1,
        "tp": 1,
    }
    assert metrics["hamming_loss"] == 0.5
    assert 0 <= metrics["micro_f1"] <= 1
    assert 0 <= metrics["macro_f1"] <= 1
    assert 0 <= metrics["weighted_f1"] <= 1


def test_multilabel_metrics_include_confusion_counts() -> None:
    truth = np.array([[1, 0]])
    predicted = np.array([[0, 1]])
    metrics = multilabel_metrics(truth, predicted, ["a", "b"])
    assert metrics["per_label"]["a"]["confusion_matrix"] == {
        "tn": 0,
        "fp": 0,
        "fn": 1,
        "tp": 0,
    }
    assert metrics["per_label"]["b"]["confusion_matrix"] == {
        "tn": 0,
        "fp": 1,
        "fn": 0,
        "tp": 0,
    }
