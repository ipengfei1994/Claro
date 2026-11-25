from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from claro.risk_engine.evaluation.metrics import binary_metrics, multilabel_metrics
from claro.risk_engine.ml.data import (
    TrainingExample,
    risk_targets,
)
from claro.risk_engine.ml.predictor import ModelPredictor
from claro.risk_engine.preprocessing import preprocess
from claro.risk_engine.rules import RuleEngine

MAX_CASES_PER_TYPE = 200


@dataclass(frozen=True, slots=True)
class ErrorCase:
    message_id: str
    error_type: str
    category: str | None
    predicted_score: float
    truth_label: str
    truth_category: str | None
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "error_type": self.error_type,
            "category": self.category,
            "predicted_score": round(self.predicted_score, 4),
            "truth_label": self.truth_label,
            "truth_category": self.truth_category,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class EvaluationOutcome:
    metrics: dict[str, Any]
    case_counts: dict[str, int]
    error_cases: tuple[ErrorCase, ...]
    message_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": self.message_count,
            "metrics": self.metrics,
            "case_counts": dict(self.case_counts),
            "error_cases": [case.to_dict() for case in self.error_cases],
            "error_case_limit_per_type": MAX_CASES_PER_TYPE,
        }


def evaluate_predictor(
    predictor: ModelPredictor,
    examples: Sequence[TrainingExample],
    labels: Sequence[str],
    rules: RuleEngine | None = None,
    *,
    train_examples: Sequence[TrainingExample] | None = None,
) -> EvaluationOutcome:
    if not examples:
        raise ValueError("evaluation requires at least one example")
    non_boundary = [item for item in examples if item.label != "boundary"]
    boundary = [item for item in examples if item.label == "boundary"]
    if not non_boundary:
        raise ValueError("evaluation requires non-boundary messages")

    probabilities: list[np.ndarray] = []
    predicted_categories: list[dict[str, float]] = []
    truth_matrix = np.zeros((len(non_boundary), len(labels)), dtype=int)
    rule_categories: list[set[str]] = []
    index = {label: position for position, label in enumerate(labels)}

    for row, example in enumerate(non_boundary):
        text = preprocess(example.content)
        prediction = predictor.predict(text)
        row_probabilities = np.asarray(
            [prediction.probabilities.get(label, 0.0) for label in labels], dtype=float
        )
        probabilities.append(row_probabilities)
        predicted_categories.append(
            {
                label: value
                for label, value in prediction.probabilities.items()
                if value >= prediction.thresholds[label]
            }
        )
        if example.label == "risk" and example.category in index:
            truth_matrix[row, index[example.category]] = 1
        if rules is not None:
            result = rules.evaluate(text)
            rule_categories.append({finding.db_category for finding in result.findings})
        else:
            rule_categories.append(set())

    probability_matrix = np.vstack(probabilities)
    threshold_array = np.asarray([predictor.thresholds[label] for label in labels])
    predicted_matrix = (probability_matrix >= threshold_array).astype(int)
    binary_truth = risk_targets(truth_matrix)
    binary_predicted = predicted_matrix.any(axis=1).astype(int)

    metrics = {
        "multilabel": multilabel_metrics(truth_matrix, predicted_matrix, labels),
        "binary": binary_metrics(binary_truth, binary_predicted),
    }
    metrics["boundary"] = _boundary_metrics(predictor, boundary)
    metrics["content_disjoint"] = _content_disjoint(
        train_examples,
        non_boundary,
        probability_matrix,
        threshold_array,
        truth_matrix,
        labels,
    )

    cases: list[ErrorCase] = []
    counts: Counter[str] = Counter()
    for row, example in enumerate(non_boundary):
        truth_risk = int(binary_truth[row])
        predicted_risk = int(binary_predicted[row])
        scores = {
            label: round(float(probability_matrix[row, position]), 4)
            for position, label in enumerate(labels)
        }
        top_label = max(scores, key=scores.get) if scores else None
        top_score = scores[top_label] if top_label else 0.0
        if truth_risk == 0 and predicted_risk == 1:
            counts["false_positive"] += 1
            if counts["false_positive"] <= MAX_CASES_PER_TYPE:
                cases.append(
                    ErrorCase(
                        message_id=example.message_id,
                        error_type="false_positive",
                        category=_first_predicted(predicted_categories[row]),
                        predicted_score=top_score,
                        truth_label=example.label,
                        truth_category=example.category,
                        detail={"probabilities": scores},
                    )
                )
        elif truth_risk == 1 and predicted_risk == 0:
            counts["false_negative"] += 1
            if counts["false_negative"] <= MAX_CASES_PER_TYPE:
                cases.append(
                    ErrorCase(
                        message_id=example.message_id,
                        error_type="false_negative",
                        category=example.category,
                        predicted_score=scores.get(example.category or "", top_score),
                        truth_label=example.label,
                        truth_category=example.category,
                        detail={"probabilities": scores},
                    )
                )
        if rules is not None:
            predicted_set = set(predicted_categories[row])
            differs = (
                rule_categories[row]
                and predicted_set
                and not (rule_categories[row] & predicted_set)
            )
            if differs:
                counts["conflicting"] += 1
                if counts["conflicting"] <= MAX_CASES_PER_TYPE:
                    cases.append(
                        ErrorCase(
                            message_id=example.message_id,
                            error_type="conflicting",
                            category=sorted(rule_categories[row])[0],
                            predicted_score=top_score,
                            truth_label=example.label,
                            truth_category=example.category,
                            detail={
                                "rule_categories": sorted(rule_categories[row]),
                                "ml_categories": sorted(predicted_set),
                            },
                        )
                    )
        if 0.42 <= top_score <= 0.58:
            counts["low_confidence"] += 1
            if counts["low_confidence"] <= MAX_CASES_PER_TYPE:
                cases.append(
                    ErrorCase(
                        message_id=example.message_id,
                        error_type="low_confidence",
                        category=top_label,
                        predicted_score=top_score,
                        truth_label=example.label,
                        truth_category=example.category,
                        detail={"probabilities": scores},
                    )
                )

    for example in boundary:
        counts["borderline"] += 1
        if counts["borderline"] <= MAX_CASES_PER_TYPE:
            text = preprocess(example.content)
            prediction = predictor.predict(text)
            cases.append(
                ErrorCase(
                    message_id=example.message_id,
                    error_type="borderline",
                    category=prediction.top_category,
                    predicted_score=prediction.risk_probability,
                    truth_label=example.label,
                    truth_category=example.category,
                    detail={"probabilities": prediction.probabilities},
                )
            )

    return EvaluationOutcome(
        metrics=metrics,
        case_counts=dict(counts),
        error_cases=tuple(cases),
        message_count=len(examples),
    )


def _first_predicted(values: dict[str, float]) -> str | None:
    return max(values, key=values.get) if values else None


def _boundary_metrics(
    predictor: ModelPredictor,
    boundary: Sequence[TrainingExample],
) -> dict[str, Any]:
    if not boundary:
        return {"messages": 0}
    flagged = 0
    max_scores: list[float] = []
    for example in boundary:
        prediction = predictor.predict(preprocess(example.content))
        if prediction.is_risk:
            flagged += 1
        max_scores.append(prediction.risk_probability)
    return {
        "messages": len(boundary),
        "flagged_as_risk": flagged,
        "flagged_ratio": round(flagged / len(boundary), 4),
        "average_max_probability": round(float(np.mean(max_scores)), 4),
        "policy": "boundary messages are excluded from precision and recall",
    }


def _content_disjoint(
    train_examples: Sequence[TrainingExample] | None,
    non_boundary: Sequence[TrainingExample],
    probability_matrix: np.ndarray,
    thresholds: np.ndarray,
    truth_matrix: np.ndarray,
    labels: Sequence[str],
) -> dict[str, Any]:
    if not train_examples:
        return {
            "messages": 0,
            "note": "train split was not supplied; content-disjoint metrics skipped",
        }
    train_hashes = {item.content_hash for item in train_examples}
    indices = [
        row for row, example in enumerate(non_boundary) if example.content_hash not in train_hashes
    ]
    if not indices:
        return {"messages": 0}
    selected_probabilities = probability_matrix[indices]
    selected_predicted = (selected_probabilities >= thresholds).astype(int)
    selected_truth = truth_matrix[indices]
    metrics = multilabel_metrics(selected_truth, selected_predicted, labels)
    binary = binary_metrics(
        risk_targets(selected_truth), selected_predicted.any(axis=1).astype(int)
    )
    return {"messages": len(indices), "multilabel": metrics, "binary": binary}
