from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from claro.risk_engine.preprocessing import PreprocessedText
from claro.risk_engine.types import ModelPrediction


class ModelLoadError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LoadedModel:
    model_id: str
    model_version: int
    algorithm: str
    labels: tuple[str, ...]
    thresholds: dict[str, float]
    metadata: dict[str, Any]
    vectorizer: Any
    classifier: Any


class ModelPredictor:
    def __init__(self, model: LoadedModel) -> None:
        self._model = model

    @property
    def model_id(self) -> str:
        return self._model.model_id

    @property
    def metadata(self) -> dict[str, Any]:
        return self._model.metadata

    @property
    def labels(self) -> tuple[str, ...]:
        return self._model.labels

    @property
    def thresholds(self) -> dict[str, float]:
        return dict(self._model.thresholds)

    @classmethod
    def from_path(cls, path: Path) -> ModelPredictor:
        if not path.is_file():
            raise ModelLoadError(f"model artifact not found: {path}")
        try:
            bundle = joblib.load(path)
            metadata = bundle["metadata"]
            labels = tuple(str(label) for label in bundle["labels"])
            thresholds = {str(label): float(value) for label, value in bundle["thresholds"].items()}
            model = LoadedModel(
                model_id=str(metadata["model_id"]),
                model_version=int(metadata["model_version"]),
                algorithm=str(metadata["algorithm"]),
                labels=labels,
                thresholds=thresholds,
                metadata=metadata,
                vectorizer=bundle["vectorizer"],
                classifier=bundle["classifier"],
            )
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise ModelLoadError(f"invalid model artifact: {path}: {error}") from error
        if set(model.labels) != set(model.thresholds):
            raise ModelLoadError("model labels and thresholds do not match")
        return cls(model)

    @classmethod
    def from_metadata_file(cls, path: Path) -> ModelPredictor:
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
            artifact = Path(metadata["artifact_path"])
            if not artifact.is_absolute():
                artifact = _project_root() / artifact
        except (OSError, KeyError, ValueError) as error:
            raise ModelLoadError(f"invalid model metadata: {path}: {error}") from error
        return cls.from_path(artifact)

    def predict(self, text: PreprocessedText) -> ModelPrediction:
        matrix = self._model.vectorizer.transform([text.ml_text])
        if hasattr(self._model.classifier, "predict_proba"):
            values = self._model.classifier.predict_proba(matrix)
        else:
            scores = self._model.classifier.decision_function(matrix)
            values = 1.0 / (1.0 + np.exp(-np.asarray(scores, dtype=float)))
        values = np.asarray(values, dtype=float)
        if values.ndim == 1:
            values = values.reshape(1, -1)
        probabilities = {
            label: round(float(values[0, index]), 6)
            for index, label in enumerate(self._model.labels)
        }
        risk_probability = max(probabilities.values(), default=0.0)
        is_risk = any(
            probabilities[label] >= self._model.thresholds[label] for label in self._model.labels
        )
        top_category = max(probabilities, key=probabilities.get) if probabilities else None
        return ModelPrediction(
            model_id=self._model.model_id,
            model_version=self._model.model_version,
            algorithm=self._model.algorithm,
            probabilities=probabilities,
            thresholds=dict(self._model.thresholds),
            risk_probability=risk_probability,
            is_risk=is_risk,
            top_category=top_category,
        )


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]
