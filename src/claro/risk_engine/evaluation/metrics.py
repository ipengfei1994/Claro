from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    hamming_loss,
    multilabel_confusion_matrix,
    precision_recall_fscore_support,
)


def binary_metrics(y_true: Sequence[int], y_pred: Sequence[int]) -> dict[str, Any]:
    truth = np.asarray(y_true, dtype=int)
    predicted = np.asarray(y_pred, dtype=int)
    if truth.size == 0:
        return {"samples": 0}
    labels = [0, 1]
    matrix = confusion_matrix(truth, predicted, labels=labels)
    tn, fp, fn, tp = (int(value) for value in matrix.ravel())
    precision, recall, f1, _ = precision_recall_fscore_support(
        truth, predicted, average="binary", zero_division=0
    )
    return {
        "samples": int(truth.size),
        "accuracy": round(float(accuracy_score(truth, predicted)), 4),
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1": round(float(f1), 4),
        "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0,
        "false_negative_rate": round(fn / (fn + tp), 4) if fn + tp else 0.0,
        "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
        "false_positives": fp,
        "false_negatives": fn,
    }


def multilabel_metrics(
    y_true: np.ndarray, y_pred: np.ndarray, labels: Sequence[str]
) -> dict[str, Any]:
    truth = np.asarray(y_true, dtype=int)
    predicted = np.asarray(y_pred, dtype=int)
    if truth.size == 0:
        return {"samples": 0, "labels": list(labels)}
    micro = precision_recall_fscore_support(truth, predicted, average="micro", zero_division=0)
    macro = precision_recall_fscore_support(truth, predicted, average="macro", zero_division=0)
    weighted = precision_recall_fscore_support(
        truth, predicted, average="weighted", zero_division=0
    )
    per_label_precision, per_label_recall, per_label_f1, per_label_support = (
        precision_recall_fscore_support(truth, predicted, average=None, zero_division=0)
    )
    matrices = multilabel_confusion_matrix(truth, predicted)
    per_label: dict[str, Any] = {}
    for index, label in enumerate(labels):
        tn, fp, fn, tp = (int(value) for value in matrices[index].ravel())
        per_label[label] = {
            "precision": round(float(per_label_precision[index]), 4),
            "recall": round(float(per_label_recall[index]), 4),
            "f1": round(float(per_label_f1[index]), 4),
            "support": int(per_label_support[index]),
            "predicted_positive": int(predicted[:, index].sum()),
            "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
        }
    return {
        "samples": int(truth.shape[0]),
        "labels": list(labels),
        "micro_precision": round(float(micro[0]), 4),
        "micro_recall": round(float(micro[1]), 4),
        "micro_f1": round(float(micro[2]), 4),
        "macro_precision": round(float(macro[0]), 4),
        "macro_recall": round(float(macro[1]), 4),
        "macro_f1": round(float(macro[2]), 4),
        "weighted_precision": round(float(weighted[0]), 4),
        "weighted_recall": round(float(weighted[1]), 4),
        "weighted_f1": round(float(weighted[2]), 4),
        "hamming_loss": round(float(hamming_loss(truth, predicted)), 4),
        "per_label": per_label,
    }


def binary_f1(y_true: Sequence[int], y_pred: Sequence[int]) -> float:
    if not len(y_true) or not len(y_pred):
        return 0.0
    return round(float(f1_score(y_true, y_pred, zero_division=0)), 4)
