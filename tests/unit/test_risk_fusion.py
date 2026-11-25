from __future__ import annotations

from pathlib import Path

import pytest

from claro.risk_engine.fusion import (
    FusionConfigurationError,
    fuse,
    load_fusion_config,
)
from claro.risk_engine.taxonomy import load_taxonomy
from claro.risk_engine.types import DetectionFinding, EvidenceSpan, LayerName, ModelPrediction

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def taxonomy():
    return load_taxonomy(PROJECT_ROOT / "config" / "risk_taxonomy.yaml")


@pytest.fixture(scope="module")
def config():
    return load_fusion_config(PROJECT_ROOT / "config" / "risk_thresholds.yaml")


def rule_finding(
    *,
    rule_id: str = "R-AD-001",
    category: str = "spam_advertising",
    db_category: str = "spam",
    score: float = 0.7,
    severity: str = "medium",
    layer: LayerName = "rule",
) -> DetectionFinding:
    return DetectionFinding(
        layer=layer,
        detector=f"{layer}.test",
        detector_version="1",
        category=category,
        db_category=db_category,
        score=score,
        confidence=0.9,
        severity=severity,
        rule_id=rule_id,
        evidence=(EvidenceSpan(text="限时广告"),),
    )


def prediction(probabilities: dict[str, float], thresholds: dict[str, float]) -> ModelPrediction:
    return ModelPrediction(
        model_id="model-1",
        model_version=1,
        algorithm="logistic_regression",
        probabilities=probabilities,
        thresholds=thresholds,
        risk_probability=max(probabilities.values()),
        is_risk=True,
        top_category=max(probabilities, key=probabilities.get),
    )


def test_single_rule_uses_severity_and_layer_weights(taxonomy, config) -> None:
    result = fuse(findings=(rule_finding(),), prediction=None, taxonomy=taxonomy, config=config)
    expected = config.severity_scores["medium"] * 0.7 * config.layer_weights["rule"]
    assert result.risk_score == pytest.approx(expected)
    assert result.risk_level == config.level_for(expected)
    assert result.suggested_action == config.action_for(expected)
    assert result.categories[0].contributions[0].layer == "rule"
    assert result.strategy == "weighted_noisy_or_max_category"


def test_rule_and_ml_combine_with_noisy_or(taxonomy, config) -> None:
    rule = rule_finding()
    ml = prediction({"spam": 0.8}, {"spam": 0.5})
    result = fuse(findings=(rule,), prediction=ml, taxonomy=taxonomy, config=config)

    rule_weighted = config.severity_scores["medium"] * 0.7 * config.layer_weights["rule"]
    ml_weighted = 0.8 * config.layer_weights["ml"]
    expected = 1 - (1 - rule_weighted) * (1 - ml_weighted)
    assert result.risk_score == pytest.approx(expected)
    assert result.risk_level == config.level_for(expected)
    assert len(result.categories[0].contributions) == 2


def test_persisted_ml_finding_is_not_counted_twice(taxonomy, config) -> None:
    ml = prediction({"spam": 0.8}, {"spam": 0.5})
    with_finding = fuse(
        findings=(rule_finding(), rule_finding(layer="ml", rule_id="ml.spam")),
        prediction=ml,
        taxonomy=taxonomy,
        config=config,
    )
    without_finding = fuse(
        findings=(rule_finding(),), prediction=ml, taxonomy=taxonomy, config=config
    )
    assert with_finding.risk_score == pytest.approx(without_finding.risk_score)


def test_ml_below_threshold_reports_rule_only_conflict(taxonomy, config) -> None:
    ml = prediction({"spam": 0.3}, {"spam": 0.5})
    result = fuse(findings=(rule_finding(),), prediction=ml, taxonomy=taxonomy, config=config)
    assert len(result.categories[0].contributions) == 1
    assert {(item.kind, item.category) for item in result.conflicts} == {("rule_only", "spam")}


def test_layer_disagreement_is_reported(taxonomy, config) -> None:
    ml = prediction({"harassment": 0.9}, {"harassment": 0.5})
    result = fuse(findings=(rule_finding(),), prediction=ml, taxonomy=taxonomy, config=config)
    kinds = {item.kind for item in result.conflicts}
    assert "layer_disagreement" in kinds
    assert "ml_only" in kinds


def test_multi_label_keeps_each_category_and_max_score(taxonomy, config) -> None:
    findings = (
        rule_finding(),
        rule_finding(
            rule_id="R-HAR-001",
            category="harassment_personal",
            db_category="harassment",
            score=0.8,
        ),
    )
    result = fuse(findings=findings, prediction=None, taxonomy=taxonomy, config=config)
    assert {item.db_category for item in result.categories} == {"spam", "harassment"}
    assert result.risk_score == pytest.approx(max(item.score for item in result.categories))
    assert result.categories[0].score >= result.categories[1].score


def test_rejects_non_increasing_level_cutoffs(tmp_path: Path) -> None:
    source = (PROJECT_ROOT / "config" / "risk_thresholds.yaml").read_text(encoding="utf-8")
    target = tmp_path / "thresholds.yaml"
    target.write_text(source.replace("normal_upper: 0.20", "normal_upper: 0.50"), encoding="utf-8")
    with pytest.raises(FusionConfigurationError, match="strictly increasing"):
        load_fusion_config(target)
