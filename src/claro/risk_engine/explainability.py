from __future__ import annotations

from typing import Any

from claro.risk_engine.preprocessing import PreprocessedText
from claro.risk_engine.types import DetectionFinding, FusionResult, ModelPrediction


def build_explanation(
    *,
    text: PreprocessedText,
    findings: tuple[DetectionFinding, ...],
    prediction: ModelPrediction | None,
    fusion: FusionResult,
    semantic_reason: str | None,
    llm_reason: str | None,
    fusion_config: dict[str, Any],
) -> dict[str, Any]:
    matched_rules = [
        {
            "rule_id": finding.rule_id,
            "name": finding.details.get("rule_name"),
            "category": finding.category,
            "db_category": finding.db_category,
            "severity": finding.severity,
            "weight": round(finding.score, 4),
            "evidence": [span.to_dict() for span in finding.evidence],
        }
        for finding in findings
        if finding.layer == "rule"
    ]
    evidence: list[dict[str, Any]] = []
    for finding in findings:
        for span in finding.evidence:
            evidence.append(
                {
                    "layer": finding.layer,
                    "source": finding.rule_id or finding.detector,
                    "category": finding.category,
                    "span": span.to_dict(),
                }
            )
    reasons = [
        {
            "category": assessment.db_category,
            "name": assessment.name,
            "score": round(assessment.score, 4),
            "level": assessment.level,
            "drivers": [
                {
                    "layer": contribution.layer,
                    "source": contribution.source,
                    "weighted_strength": round(contribution.weighted_strength, 4),
                }
                for contribution in assessment.contributions
            ],
        }
        for assessment in fusion.categories
    ]
    layers = [
        {
            "layer": "rule",
            "status": "available" if findings else "available_no_match",
            "matched": len(matched_rules),
        },
        {
            "layer": "ml",
            "status": "available" if prediction is not None else "not_available",
            "reason": None if prediction is not None else "no active model",
            "model": prediction.to_dict() if prediction is not None else None,
        },
        {
            "layer": "semantic",
            "status": "not_available" if semantic_reason else "disabled",
            "reason": semantic_reason,
        },
        {
            "layer": "llm",
            "status": "disabled" if llm_reason else "available",
            "reason": llm_reason,
        },
    ]
    return {
        "text": {
            "original": text.original,
            "normalized": text.normalized,
            "ml_text": text.ml_text,
            "features": text.features.to_dict(),
            "preprocessing": text.metadata,
        },
        "question_answers": {
            "why_flagged": reasons,
            "matched_rules": matched_rules,
            "evidence": evidence,
            "models_involved": (
                {
                    "model_id": prediction.model_id,
                    "algorithm": prediction.algorithm,
                    "probabilities": prediction.probabilities,
                }
                if prediction is not None
                else {}
            ),
            "score_formation": list(fusion.fusion_trace),
            "level_decision": {
                "risk_score": round(fusion.risk_score, 4),
                "risk_level": fusion.risk_level,
                "suggested_action": fusion.suggested_action,
                "thresholds": fusion_config,
            },
            "conflicts": [item.to_dict() for item in fusion.conflicts],
        },
        "layers": layers,
        "disclaimer": (
            "Fusion is a configurable decision rule, not a calibrated probability. "
            "Synthetic dataset results do not establish production accuracy."
        ),
    }
