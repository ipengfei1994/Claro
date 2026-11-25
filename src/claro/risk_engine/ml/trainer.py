from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import structlog
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.svm import LinearSVC

from claro.risk_engine.evaluation.metrics import (
    binary_metrics,
    multilabel_metrics,
)
from claro.risk_engine.ml.data import (
    TrainingExample,
    content_disjoint_subset,
    labels_matrix,
    leakage_report,
    risk_targets,
)
from claro.risk_engine.preprocessing import preprocess

logger = structlog.get_logger(__name__)

THRESHOLD_GRID = tuple(round(0.2 + 0.05 * index, 2) for index in range(15))
DEFAULT_THRESHOLD = 0.5


class TrainingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    algorithm: str = "logistic_regression"
    c_values: tuple[float, ...] = (1.0, 4.0)
    min_df: int = 2
    max_features: int = 100_000
    ngram_min: int = 1
    ngram_max: int = 4
    seed: int = 20261125
    dataset_name: str = "unknown"
    model_version: int = 1


@dataclass(frozen=True, slots=True)
class TrainingOutcome:
    model_id: str
    algorithm: str
    dataset_name: str
    model_version: int
    artifact_path: str
    bundle_path: Path
    metadata_path: Path
    metadata: dict[str, Any]
    validation_metrics: dict[str, Any]
    test_metrics: dict[str, Any]
    thresholds: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "algorithm": self.algorithm,
            "dataset": self.dataset_name,
            "version": self.model_version,
            "artifact_path": self.artifact_path,
            "validation": self.validation_metrics,
            "test": self.test_metrics,
            "thresholds": {key: round(value, 2) for key, value in self.thresholds.items()},
        }


def train_risk_model(
    examples: Sequence[TrainingExample],
    labels: Sequence[str],
    config: TrainingConfig,
    models_dir: Path,
    *,
    project_root: Path | None = None,
) -> TrainingOutcome:
    if not labels:
        raise TrainingError("at least one risk label is required")
    if config.algorithm not in {"logistic_regression", "linear_svm"}:
        raise TrainingError(f"unsupported algorithm: {config.algorithm}")

    splits = _split(examples)
    train = [item for item in splits.get("train", []) if item.label != "boundary"]
    validation = [item for item in splits.get("validation", []) if item.label != "boundary"]
    test = [item for item in splits.get("test", []) if item.label != "boundary"]
    boundary = [item for item in splits.get("test", []) if item.label == "boundary"]
    if not train or not validation or not test:
        raise TrainingError(
            "train/validation/test splits must all contain non-boundary labeled messages"
        )
    if len({item.player_ref for item in train} & {item.player_ref for item in test}):
        raise TrainingError("player leakage between train and test splits")

    train_texts, train_y = labels_matrix(train, labels)
    validation_texts, validation_y = labels_matrix(validation, labels)
    test_texts, test_y = labels_matrix(test, labels)

    vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(config.ngram_min, config.ngram_max),
        min_df=config.min_df,
        max_features=config.max_features,
        sublinear_tf=True,
        lowercase=False,
    )
    train_x = vectorizer.fit_transform(train_texts)
    validation_x = vectorizer.transform(validation_texts)

    best_c, best_model, best_score = None, None, -1.0
    candidate_results: list[dict[str, Any]] = []
    for c_value in config.c_values:
        model = _new_classifier(config.algorithm, c_value, config.seed)
        model.fit(train_x, train_y)
        probabilities = _probabilities(model, validation_x)
        predicted = (probabilities >= DEFAULT_THRESHOLD).astype(int)
        metrics = multilabel_metrics(validation_y, predicted, labels)
        candidate_results.append({"c": c_value, "macro_f1": metrics.get("macro_f1", 0.0)})
        score = float(metrics.get("macro_f1", 0.0))
        if score > best_score:
            best_c, best_model, best_score = c_value, model, score
    if best_model is None or best_c is None:
        raise TrainingError("no candidate model was trained")

    validation_probabilities = _probabilities(best_model, validation_x)
    thresholds = _tune_thresholds(validation_probabilities, validation_y, labels)
    validation_metrics = _evaluate(validation_y, validation_probabilities, thresholds, labels)

    combined = train + validation
    combined_texts, combined_y = labels_matrix(combined, labels)
    final_vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(config.ngram_min, config.ngram_max),
        min_df=config.min_df,
        max_features=config.max_features,
        sublinear_tf=True,
        lowercase=False,
    )
    combined_x = final_vectorizer.fit_transform(combined_texts)
    final_model = _new_classifier(config.algorithm, best_c, config.seed)
    final_model.fit(combined_x, combined_y)

    test_probabilities = _probabilities(final_model, final_vectorizer.transform(test_texts))
    test_metrics = _evaluate(test_y, test_probabilities, thresholds, labels)
    test_metrics["leakage"] = leakage_report(splits.get("train", []), splits.get("test", []))

    disjoint = content_disjoint_subset(
        splits.get("train", []),
        [item for item in splits.get("test", []) if item.label != "boundary"],
    )
    if disjoint:
        disjoint_texts, disjoint_y = labels_matrix(disjoint, labels)
        disjoint_probabilities = _probabilities(
            final_model, final_vectorizer.transform(disjoint_texts)
        )
        test_metrics["content_disjoint"] = _evaluate(
            disjoint_y, disjoint_probabilities, thresholds, labels
        )
        test_metrics["content_disjoint"]["messages"] = len(disjoint)
    else:
        test_metrics["content_disjoint"] = {"messages": 0}

    boundary_summary = _boundary_summary(final_model, final_vectorizer, boundary, thresholds)
    test_metrics["boundary"] = boundary_summary

    model_id = _model_id(config.dataset_name, config.algorithm)
    artifact_directory = models_dir / "risk_ml" / model_id
    artifact_directory.mkdir(parents=True, exist_ok=True)
    bundle_path = artifact_directory / "model.joblib"
    metadata_path = artifact_directory / "metadata.json"
    metadata = {
        "model_id": model_id,
        "model_name": f"risk-{config.algorithm}",
        "model_version": config.model_version,
        "algorithm": config.algorithm,
        "training_dataset": config.dataset_name,
        "trained_at": datetime.now(UTC).isoformat(),
        "feature_config": {
            "analyzer": "char_wb",
            "ngram_range": [config.ngram_min, config.ngram_max],
            "min_df": config.min_df,
            "max_features": config.max_features,
            "sublinear_tf": True,
            "vocabulary_size": len(final_vectorizer.vocabulary_),
        },
        "hyperparameters": {"C": best_c, "class_weight": "balanced"},
        "candidate_results": candidate_results,
        "evaluation_metrics": {
            "validation": validation_metrics,
            "test": test_metrics,
        },
        "thresholds": thresholds,
        "labels": list(labels),
        "split_sizes": {
            "train": len(train),
            "validation": len(validation),
            "test": len(test),
            "boundary_test": len(boundary),
        },
        "synthetic_dataset": True,
        "notice": (
            "Metrics are computed on a synthetic template dataset and do not establish "
            "production accuracy."
        ),
    }
    temporary_bundle = artifact_directory / "model.joblib.tmp"
    joblib.dump(
        {
            "vectorizer": final_vectorizer,
            "classifier": final_model,
            "labels": list(labels),
            "thresholds": thresholds,
            "metadata": metadata,
        },
        temporary_bundle,
        compress=3,
    )
    shutil.move(str(temporary_bundle), bundle_path)
    metadata["artifact_path"] = _relative_path(bundle_path, project_root)
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info(
        "risk_model_trained",
        model_id=model_id,
        dataset=config.dataset_name,
        algorithm=config.algorithm,
        macro_f1=test_metrics.get("macro_f1"),
    )
    return TrainingOutcome(
        model_id=model_id,
        algorithm=config.algorithm,
        dataset_name=config.dataset_name,
        model_version=config.model_version,
        artifact_path=metadata["artifact_path"],
        bundle_path=bundle_path,
        metadata_path=metadata_path,
        metadata=metadata,
        validation_metrics=validation_metrics,
        test_metrics=test_metrics,
        thresholds=thresholds,
    )


def _split(examples: Sequence[TrainingExample]) -> dict[str, list[TrainingExample]]:
    grouped: dict[str, list[TrainingExample]] = {}
    for example in examples:
        grouped.setdefault(example.split, []).append(example)
    return grouped


def _new_classifier(algorithm: str, c_value: float, seed: int) -> Any:
    if algorithm == "logistic_regression":
        estimator = LogisticRegression(
            C=c_value,
            max_iter=2_000,
            class_weight="balanced",
            random_state=seed,
        )
    else:
        estimator = LinearSVC(
            C=c_value,
            class_weight="balanced",
            random_state=seed,
            max_iter=10_000,
        )
    return OneVsRestClassifier(estimator)


def _probabilities(model: Any, matrix: Any) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        values = model.predict_proba(matrix)
    else:
        scores = model.decision_function(matrix)
        values = 1.0 / (1.0 + np.exp(-scores))
    values = np.asarray(values, dtype=float)
    if values.ndim == 1:
        values = values.reshape(-1, 1)
    return np.clip(values, 0.0, 1.0)


def _tune_thresholds(
    probabilities: np.ndarray, truth: np.ndarray, labels: Sequence[str]
) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for index, label in enumerate(labels):
        positives = int(truth[:, index].sum())
        if positives == 0:
            thresholds[label] = DEFAULT_THRESHOLD
            continue
        best_threshold, best_f1 = DEFAULT_THRESHOLD, -1.0
        for threshold in THRESHOLD_GRID:
            predicted = (probabilities[:, index] >= threshold).astype(int)
            tp = int(((predicted == 1) & (truth[:, index] == 1)).sum())
            fp = int(((predicted == 1) & (truth[:, index] == 0)).sum())
            fn = int(((predicted == 0) & (truth[:, index] == 1)).sum())
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            if f1 > best_f1:
                best_threshold, best_f1 = threshold, f1
        thresholds[label] = best_threshold
    return thresholds


def _evaluate(
    truth: np.ndarray,
    probabilities: np.ndarray,
    thresholds: dict[str, float],
    labels: Sequence[str],
) -> dict[str, Any]:
    threshold_array = np.asarray([thresholds[label] for label in labels])
    predicted = (probabilities >= threshold_array).astype(int)
    multilabel = multilabel_metrics(truth, predicted, labels)
    binary = binary_metrics(risk_targets(truth), predicted.max(axis=1) if predicted.size else [])
    return {"multilabel": multilabel, "binary": binary}


def _boundary_summary(
    model: Any,
    vectorizer: TfidfVectorizer,
    boundary: Sequence[TrainingExample],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    if not boundary:
        return {"messages": 0}
    texts = [preprocess(item.content).ml_text for item in boundary]
    probabilities = _probabilities(model, vectorizer.transform(texts))
    labels = list(thresholds)
    threshold_array = np.asarray([thresholds[label] for label in labels])
    flagged = (probabilities >= threshold_array).any(axis=1)
    return {
        "messages": len(boundary),
        "flagged_as_risk": int(flagged.sum()),
        "flagged_ratio": round(float(flagged.mean()), 4),
        "average_max_probability": round(float(probabilities.max(axis=1).mean()), 4),
        "policy": "boundary examples are excluded from train and from precision/recall metrics",
    }


def _model_id(dataset_name: str, algorithm: str) -> str:
    token = "".join(char if char.isalnum() else "-" for char in dataset_name)[-40:]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{algorithm}-{token}-{stamp}"


def _relative_path(path: Path, project_root: Path | None) -> str:
    if project_root is not None:
        try:
            return path.resolve().relative_to(project_root.resolve()).as_posix()
        except ValueError:
            pass
    return path.resolve().as_posix()
