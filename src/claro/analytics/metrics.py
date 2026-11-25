"""Pure metric functions shared by all analytics services.

These functions have no database dependency so they can be validated against
small, hand-checkable fixtures in unit tests.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from math import isfinite
from statistics import mean, pstdev
from typing import Any

from claro.analytics.definitions import RESTRICTIVE_ACTIONS

_RESTRICTIVENESS = {action: index for index, action in enumerate(RESTRICTIVE_ACTIONS)}


def as_int(value: Any) -> int:
    """Coerce a database count (int, Decimal or numeric string) to int."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return 0


def as_float(value: Any) -> float | None:
    """Coerce a numeric database value to float, returning None when invalid."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def ratio(numerator: Any, denominator: Any) -> float | None:
    """Return numerator/denominator, or None when the denominator is zero."""
    total = as_int(denominator)
    if total <= 0:
        return None
    return round(as_int(numerator) / total, 6)


def risk_rate(total_messages: Any, risk_messages: Any) -> dict[str, Any]:
    """Canonical Risk Rate: distinct risk messages / distinct messages."""
    total = as_int(total_messages)
    risk = as_int(risk_messages)
    return {
        "risk_messages": risk,
        "total_messages": total,
        "risk_rate": ratio(risk, total),
        "definition": "risk_messages / total_messages",
    }


def dedupe_by(rows: Iterable[Mapping[str, Any]], key: str) -> list[Mapping[str, Any]]:
    """Deduplicate rows by a single key, keeping the first occurrence."""
    seen: set[Any] = set()
    unique: list[Mapping[str, Any]] = []
    for row in rows:
        value = row.get(key)
        if value in seen:
            continue
        seen.add(value)
        unique.append(row)
    return unique


def count_by(rows: Iterable[Mapping[str, Any]], key: str) -> dict[str, int]:
    """Count rows by a key without double counting duplicate identifiers."""
    counts: dict[str, int] = {}
    for row in rows:
        label = str(row.get(key) or "unspecified")
        counts[label] = counts.get(label, 0) + 1
    return counts


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Linear-interpolation percentile (same convention as PostgreSQL percentile_cont)."""
    clean = sorted(value for value in values if isfinite(value))
    if not clean:
        return None
    if len(clean) == 1:
        return round(clean[0], 3)
    position = (len(clean) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(clean) - 1)
    weight = position - lower
    result = clean[lower] * (1 - weight) + clean[upper] * weight
    return round(result, 3)


def duration_stats(seconds: Sequence[float]) -> dict[str, Any]:
    """Return count, average, P50 and P90 for completed durations only."""
    clean = [float(value) for value in seconds if value is not None and value >= 0]
    if not clean:
        return {"samples": 0, "avg_seconds": None, "p50_seconds": None, "p90_seconds": None}
    return {
        "samples": len(clean),
        "avg_seconds": round(mean(clean), 3),
        "p50_seconds": percentile(clean, 0.5),
        "p90_seconds": percentile(clean, 0.9),
    }


def binary_confusion(pairs: Iterable[tuple[bool, bool]]) -> dict[str, int]:
    """Build a binary confusion matrix from (is_truth_positive, is_predicted_positive)."""
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
    return matrix


def classification_metrics(matrix: Mapping[str, int]) -> dict[str, Any]:
    """Derive precision, recall, F1, FPR, FNR and accuracy from a confusion matrix."""
    tp, fp, fn, tn = (as_int(matrix.get(key)) for key in ("tp", "fp", "fn", "tn"))
    total = tp + fp + fn + tn
    return {
        "samples": total,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "precision": ratio(tp, tp + fp),
        "recall": ratio(tp, tp + fn),
        "f1": _f1(tp, fp, fn),
        "false_positive_rate": ratio(fp, fp + tn),
        "false_negative_rate": ratio(fn, fn + tp),
        "accuracy": ratio(tp + tn, total),
    }


def _f1(tp: int, fp: int, fn: int) -> float | None:
    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    if precision is None or recall is None or precision + recall == 0:
        return None
    return round(2 * precision * recall / (precision + recall), 6)


def predicted_positive(action: str | None) -> bool:
    """Binary replay semantics: only ``allow`` is a negative prediction."""
    return str(action or "allow").lower() != "allow"


def truth_positive(label: str | None) -> bool:
    """Binary replay semantics: boundary is deliberately counted as negative."""
    return str(label or "").lower() == "risk"


def action_diff(baseline: str | None, candidate: str | None) -> str:
    """Classify a per-message action change for replay reporting."""
    if baseline == candidate:
        return "unchanged"
    baseline_rank = _RESTRICTIVENESS.get(str(baseline), -1)
    candidate_rank = _RESTRICTIVENESS.get(str(candidate), -1)
    if candidate_rank > baseline_rank:
        return "stricter"
    if candidate_rank < baseline_rank:
        return "looser"
    return "changed"


def anomaly_peaks(values: Sequence[float], sigma: float = 3.0) -> list[int]:
    """Return indices of values above mean + sigma * standard deviation."""
    if len(values) < 3:
        return []
    average = mean(values)
    deviation = pstdev(values)
    if deviation == 0:
        return []
    threshold = average + sigma * deviation
    return [index for index, value in enumerate(values) if value > threshold]


def low_sample(total_messages: Any, threshold: int) -> bool:
    """Flag a dimension member with insufficient messages for interpretation."""
    return as_int(total_messages) < threshold
