from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

LayerName = Literal["rule", "ml", "semantic", "llm"]


@dataclass(frozen=True, slots=True)
class EvidenceSpan:
    text: str
    start: int | None = None
    end: int | None = None
    source: str = "normalized"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class DetectionFinding:
    layer: LayerName
    detector: str
    detector_version: str
    category: str
    db_category: str
    score: float
    confidence: float
    severity: str | None = None
    rule_id: str | None = None
    evidence: tuple[EvidenceSpan, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 1:
            raise ValueError("finding score must be within [0, 1]")
        if not 0 <= self.confidence <= 1:
            raise ValueError("finding confidence must be within [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "detector": self.detector,
            "detector_version": self.detector_version,
            "category": self.category,
            "db_category": self.db_category,
            "score": round(self.score, 4),
            "confidence": round(self.confidence, 4),
            "severity": self.severity,
            "rule_id": self.rule_id,
            "evidence": [span.to_dict() for span in self.evidence],
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class ModelPrediction:
    model_id: str
    model_version: int
    algorithm: str
    probabilities: dict[str, float]
    thresholds: dict[str, float]
    risk_probability: float
    is_risk: bool
    top_category: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "algorithm": self.algorithm,
            "probabilities": {key: round(value, 4) for key, value in self.probabilities.items()},
            "thresholds": {key: round(value, 4) for key, value in self.thresholds.items()},
            "risk_probability": round(self.risk_probability, 4),
            "is_risk": self.is_risk,
            "top_category": self.top_category,
        }


@dataclass(frozen=True, slots=True)
class Contribution:
    layer: LayerName
    source: str
    taxonomy_category: str
    raw_strength: float
    weighted_strength: float
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "source": self.source,
            "taxonomy_category": self.taxonomy_category,
            "raw_strength": round(self.raw_strength, 4),
            "weighted_strength": round(self.weighted_strength, 4),
            "confidence": round(self.confidence, 4),
        }


@dataclass(frozen=True, slots=True)
class CategoryAssessment:
    taxonomy_category: str
    db_category: str
    name: str
    score: float
    level: str
    contributions: tuple[Contribution, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.taxonomy_category,
            "db_category": self.db_category,
            "name": self.name,
            "score": round(self.score, 4),
            "level": self.level,
            "contributions": [item.to_dict() for item in self.contributions],
        }


@dataclass(frozen=True, slots=True)
class Conflict:
    kind: str
    category: str | None
    detail: str
    rule_score: float | None = None
    ml_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "category": self.category,
            "detail": self.detail,
            "rule_score": self.rule_score,
            "ml_score": self.ml_score,
        }


@dataclass(frozen=True, slots=True)
class FusionResult:
    risk_score: float
    risk_level: str
    suggested_action: str
    confidence: float
    categories: tuple[CategoryAssessment, ...]
    conflicts: tuple[Conflict, ...]
    fusion_trace: tuple[dict[str, Any], ...]
    strategy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_score": round(self.risk_score, 4),
            "risk_level": self.risk_level,
            "suggested_action": self.suggested_action,
            "confidence": round(self.confidence, 4),
            "categories": [item.to_dict() for item in self.categories],
            "conflicts": [item.to_dict() for item in self.conflicts],
            "fusion_trace": list(self.fusion_trace),
            "strategy": self.strategy,
        }


@dataclass(frozen=True, slots=True)
class RiskResult:
    id: UUID
    message_id: UUID
    dataset_id: UUID | None
    risk_score: float
    risk_level: str
    suggested_action: str
    confidence: float
    categories: tuple[CategoryAssessment, ...]
    detection_methods: tuple[str, ...]
    findings: tuple[DetectionFinding, ...]
    explanation: dict[str, Any]
    model_id: str | None
    timings_ms: dict[str, float]
    detected_at: datetime
    is_synthetic: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_result_id": str(self.id),
            "message_id": str(self.message_id),
            "dataset_id": str(self.dataset_id) if self.dataset_id else None,
            "risk_score": round(self.risk_score, 4),
            "risk_level": self.risk_level,
            "suggested_action": self.suggested_action,
            "confidence": round(self.confidence, 4),
            "categories": [item.to_dict() for item in self.categories],
            "detection_methods": list(self.detection_methods),
            "model_id": self.model_id,
            "timings_ms": {key: round(value, 3) for key, value in self.timings_ms.items()},
            "detected_at": self.detected_at.isoformat(),
            "is_synthetic": self.is_synthetic,
            "explanation": self.explanation,
        }


@dataclass(frozen=True, slots=True)
class DetectionOutcome:
    result: RiskResult
    created: bool

    @property
    def status(self) -> Literal["processed", "duplicate"]:
        return "processed" if self.created else "duplicate"
