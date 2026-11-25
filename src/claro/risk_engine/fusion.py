from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from claro.domain.enums import DecisionAction, RiskSeverity
from claro.risk_engine.taxonomy import RiskTaxonomy
from claro.risk_engine.types import (
    CategoryAssessment,
    Conflict,
    Contribution,
    DetectionFinding,
    FusionResult,
    ModelPrediction,
)

STRATEGY = "weighted_noisy_or_max_category"


class FusionConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FusionConfig:
    normal_upper: float
    low_upper: float
    medium_upper: float
    high_upper: float
    allow_below: float
    warn_below: float
    review_below: float
    block_below: float
    restrictive_action: str
    layer_weights: dict[str, float]
    severity_scores: dict[str, float]
    ml_min_probability: float
    conflict_gap: float
    max_category_score: float
    minimum_confidence: float

    def level_for(self, score: float) -> str:
        if score < self.normal_upper:
            return RiskSeverity.NORMAL.value
        if score < self.low_upper:
            return RiskSeverity.LOW.value
        if score < self.medium_upper:
            return RiskSeverity.MEDIUM.value
        if score < self.high_upper:
            return RiskSeverity.HIGH.value
        return RiskSeverity.CRITICAL.value

    def action_for(self, score: float) -> str:
        if score < self.allow_below:
            return DecisionAction.ALLOW.value
        if score < self.warn_below:
            return DecisionAction.WARN.value
        if score < self.review_below:
            return DecisionAction.REVIEW.value
        if score < self.block_below:
            return DecisionAction.BLOCK.value
        return self.restrictive_action

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": STRATEGY,
            "levels": {
                "normal_upper": self.normal_upper,
                "low_upper": self.low_upper,
                "medium_upper": self.medium_upper,
                "high_upper": self.high_upper,
            },
            "actions": {
                "allow_below": self.allow_below,
                "warn_below": self.warn_below,
                "review_below": self.review_below,
                "block_below": self.block_below,
                "else": self.restrictive_action,
            },
            "layer_weights": dict(self.layer_weights),
            "severity_scores": dict(self.severity_scores),
            "ml_min_probability": self.ml_min_probability,
            "conflict_gap": self.conflict_gap,
            "max_category_score": self.max_category_score,
        }


def load_fusion_config(path: Path) -> FusionConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise FusionConfigurationError(f"thresholds file is unreadable: {path}") from error
    except yaml.YAMLError as error:
        raise FusionConfigurationError(f"thresholds file is not valid YAML: {error}") from error
    if not isinstance(raw, dict):
        raise FusionConfigurationError("thresholds root must be a mapping")
    levels = _mapping(raw, "levels")
    actions = _mapping(raw, "actions")
    config = FusionConfig(
        normal_upper=_number(levels, "normal_upper"),
        low_upper=_number(levels, "low_upper"),
        medium_upper=_number(levels, "medium_upper"),
        high_upper=_number(levels, "high_upper"),
        allow_below=_number(actions, "allow_below"),
        warn_below=_number(actions, "warn_below"),
        review_below=_number(actions, "review_below"),
        block_below=_number(actions, "block_below"),
        restrictive_action=str(actions.get("else", "restrict")),
        layer_weights=_weights(raw, "layer_weights"),
        severity_scores=_severity_scores(raw),
        ml_min_probability=_number(raw, "ml_min_probability"),
        conflict_gap=_number(raw, "conflict_gap"),
        max_category_score=_number(raw, "max_category_score"),
        minimum_confidence=_number(raw, "minimum_confidence"),
    )
    _validate(config)
    return config


def _mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise FusionConfigurationError(f"thresholds field '{key}' must be a mapping")
    return value


def _number(data: dict[str, Any], key: str) -> float:
    value = data.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
        raise FusionConfigurationError(f"thresholds field '{key}' must be within [0, 1]")
    return float(value)


def _weights(data: dict[str, Any], key: str) -> dict[str, float]:
    raw = _mapping(data, key)
    expected = {"rule", "ml", "semantic", "llm"}
    if set(raw) != expected:
        raise FusionConfigurationError(f"layer weights must define exactly {sorted(expected)}")
    result = {}
    for layer, value in raw.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
            raise FusionConfigurationError(f"layer weight '{layer}' must be within [0, 1]")
        result[layer] = float(value)
    return result


def _severity_scores(data: dict[str, Any]) -> dict[str, float]:
    raw = _mapping(data, "severity_scores")
    expected = {item.value for item in RiskSeverity if item is not RiskSeverity.NORMAL}
    if set(raw) != expected:
        raise FusionConfigurationError(f"severity_scores must define {sorted(expected)}")
    result = {}
    for severity, value in raw.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
            raise FusionConfigurationError(f"severity score '{severity}' must be within [0, 1]")
        result[severity] = float(value)
    return result


def _validate(config: FusionConfig) -> None:
    level_cutoffs = [
        config.normal_upper,
        config.low_upper,
        config.medium_upper,
        config.high_upper,
    ]
    action_cutoffs = [
        config.allow_below,
        config.warn_below,
        config.review_below,
        config.block_below,
    ]
    if level_cutoffs != sorted(level_cutoffs) or len(set(level_cutoffs)) != len(level_cutoffs):
        raise FusionConfigurationError("risk level cutoffs must be strictly increasing")
    if action_cutoffs != sorted(action_cutoffs) or len(set(action_cutoffs)) != len(action_cutoffs):
        raise FusionConfigurationError("action cutoffs must be strictly increasing")
    if config.restrictive_action not in {item.value for item in DecisionAction}:
        raise FusionConfigurationError("restrictive action is not a valid decision action")


def fuse(
    *,
    findings: tuple[DetectionFinding, ...],
    prediction: ModelPrediction | None,
    taxonomy: RiskTaxonomy,
    config: FusionConfig,
) -> FusionResult:
    contributions: dict[str, list[Contribution]] = defaultdict(list)
    evidence_by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for finding in findings:
        if finding.layer == "ml":
            # ML contributions are derived from the raw prediction below, so
            # persisted ML findings must not be weighted a second time.
            continue
        weighted = _weighted_strength(finding, config)
        if weighted <= 0:
            continue
        contributions[finding.db_category].append(
            Contribution(
                layer=finding.layer,
                source=finding.rule_id or finding.detector,
                taxonomy_category=finding.category,
                raw_strength=finding.score,
                weighted_strength=weighted,
                confidence=finding.confidence,
            )
        )
        evidence_by_category[finding.db_category].append(
            {
                "layer": finding.layer,
                "source": finding.rule_id or finding.detector,
                "strength": round(finding.score, 4),
                "severity": finding.severity,
                "evidence": [span.to_dict() for span in finding.evidence],
            }
        )

    ml_hits: dict[str, float] = {}
    ml_below_threshold: dict[str, float] = {}
    if prediction is not None:
        for db_category, probability in prediction.probabilities.items():
            threshold = max(
                prediction.thresholds.get(db_category, config.ml_min_probability),
                config.ml_min_probability,
            )
            if probability >= threshold:
                ml_hits[db_category] = probability
                weighted = probability * config.layer_weights["ml"]
                contributions[db_category].append(
                    Contribution(
                        layer="ml",
                        source=f"ml.{prediction.algorithm}",
                        taxonomy_category=db_category,
                        raw_strength=probability,
                        weighted_strength=weighted,
                        confidence=probability,
                    )
                )
                evidence_by_category[db_category].append(
                    {
                        "layer": "ml",
                        "source": prediction.model_id,
                        "strength": round(probability, 4),
                        "threshold": round(threshold, 4),
                        "evidence": [],
                    }
                )
            else:
                ml_below_threshold[db_category] = probability

    assessments: list[CategoryAssessment] = []
    trace: list[dict[str, Any]] = []
    for db_category, items in contributions.items():
        score = _noisy_or(item.weighted_strength for item in items)
        score = min(score, config.max_category_score)
        if score < 0.01:
            continue
        assessments.append(
            CategoryAssessment(
                taxonomy_category=db_category,
                db_category=db_category,
                name=taxonomy.db_category_name(db_category),
                score=score,
                level=config.level_for(score),
                contributions=tuple(items),
            )
        )
        trace.append(
            {
                "category": db_category,
                "name": taxonomy.db_category_name(db_category),
                "contributions": [item.to_dict() for item in items],
                "formula": "1 - PRODUCT(1 - layer_weight * strength)",
                "raw_rule_strength": _noisy_or(
                    item.raw_strength for item in items if item.layer == "rule"
                ),
                "ml_probability": ml_hits.get(db_category),
                "score": round(score, 4),
                "level": config.level_for(score),
            }
        )
    assessments.sort(key=lambda item: item.score, reverse=True)
    overall = max((item.score for item in assessments), default=0.0)
    level = config.level_for(overall)
    action = config.action_for(overall)
    confidence = _confidence(assessments, prediction, config)
    conflicts = _conflicts(assessments, ml_hits, ml_below_threshold, config)

    return FusionResult(
        risk_score=overall,
        risk_level=level,
        suggested_action=action,
        confidence=confidence,
        categories=tuple(assessments),
        conflicts=tuple(conflicts),
        fusion_trace=tuple(trace),
        strategy=STRATEGY,
    )


def _weighted_strength(finding: DetectionFinding, config: FusionConfig) -> float:
    base = finding.score
    if finding.layer == "rule":
        severity = finding.severity or "medium"
        base = config.severity_scores.get(severity, 0.5) * finding.score
    return min(base * config.layer_weights.get(finding.layer, 0.5), 0.999)


def _noisy_or(values: Any) -> float:
    product = 1.0
    any_value = False
    for value in values:
        any_value = True
        product *= 1.0 - max(0.0, min(1.0, value))
    return 0.0 if not any_value else 1.0 - product


def _confidence(
    assessments: list[CategoryAssessment],
    prediction: ModelPrediction | None,
    config: FusionConfig,
) -> float:
    confidences = [
        contribution.confidence
        for assessment in assessments
        for contribution in assessment.contributions
    ]
    if confidences:
        value = max(confidences)
    elif prediction is not None:
        value = max(0.0, 1.0 - prediction.risk_probability)
    else:
        value = 0.5
    return round(max(config.minimum_confidence, min(1.0, value)), 4)


def _conflicts(
    assessments: list[CategoryAssessment],
    ml_hits: dict[str, float],
    ml_below_threshold: dict[str, float],
    config: FusionConfig,
) -> list[Conflict]:
    rule_categories = {
        assessment.db_category
        for assessment in assessments
        if any(item.layer == "rule" for item in assessment.contributions)
    }
    conflicts: list[Conflict] = []
    if rule_categories and ml_hits and not (rule_categories & set(ml_hits)):
        conflicts.append(
            Conflict(
                kind="layer_disagreement",
                category=None,
                detail=(
                    "Rules and ML identify different categories: "
                    f"rules={sorted(rule_categories)}, ml={sorted(ml_hits)}"
                ),
            )
        )
    for category in sorted(rule_categories):
        if category not in ml_hits and category in ml_below_threshold:
            conflicts.append(
                Conflict(
                    kind="rule_only",
                    category=category,
                    detail="Rule evidence present while ML probability is below threshold",
                    ml_score=ml_below_threshold[category],
                )
            )
    for category in sorted(set(ml_hits) - rule_categories):
        if any(assessment.db_category == category for assessment in assessments):
            conflicts.append(
                Conflict(
                    kind="ml_only",
                    category=category,
                    detail="ML prediction has no supporting rule match",
                    ml_score=ml_hits[category],
                )
            )
    for assessment in assessments:
        rule_strength = _noisy_or(
            item.raw_strength for item in assessment.contributions if item.layer == "rule"
        )
        ml_score = ml_hits.get(assessment.db_category)
        if ml_score is not None and abs(rule_strength - ml_score) >= config.conflict_gap:
            conflicts.append(
                Conflict(
                    kind="score_gap",
                    category=assessment.db_category,
                    detail="Rule strength and ML probability differ beyond the configured gap",
                    rule_score=rule_strength,
                    ml_score=ml_score,
                )
            )
    return conflicts
