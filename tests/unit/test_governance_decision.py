"""Unit tests for governance decision routing and explainability."""

from __future__ import annotations

import pytest

from claro.domain.enums import DecisionAction, GovernanceDecisionStatus, RiskSeverity
from claro.governance.decision import (
    DecisionThresholds,
    decide_governance_action,
)


@pytest.mark.parametrize(
    ("action", "level", "confidence", "expected", "review"),
    [
        (
            DecisionAction.ALLOW.value,
            RiskSeverity.NORMAL.value,
            0.99,
            DecisionAction.ALLOW.value,
            False,
        ),
        (
            DecisionAction.WARN.value,
            RiskSeverity.MEDIUM.value,
            0.90,
            DecisionAction.WARN.value,
            False,
        ),
        (
            DecisionAction.REVIEW.value,
            RiskSeverity.HIGH.value,
            0.90,
            DecisionAction.REVIEW.value,
            True,
        ),
        (
            DecisionAction.BLOCK.value,
            RiskSeverity.HIGH.value,
            0.95,
            DecisionAction.BLOCK.value,
            False,
        ),
    ],
)
def test_auto_decision_paths(
    action: str, level: str, confidence: float, expected: str, review: bool
) -> None:
    result = decide_governance_action(
        evaluated_action=action,
        risk_level=level,
        risk_score=0.7,
        confidence=confidence,
    )
    assert result.action == expected
    assert result.requires_review is review
    assert result.decision_status == (
        GovernanceDecisionStatus.PENDING_REVIEW.value
        if review
        else GovernanceDecisionStatus.AUTO_DECIDED.value
    )
    assert result.reason


def test_high_severity_low_confidence_is_reviewed() -> None:
    result = decide_governance_action(
        evaluated_action=DecisionAction.PERM_BAN.value,
        risk_level=RiskSeverity.CRITICAL.value,
        risk_score=0.99,
        confidence=0.40,
    )
    assert result.action == DecisionAction.REVIEW.value
    assert result.requires_review is True
    assert result.downgraded is True
    assert result.original_action == DecisionAction.PERM_BAN.value
    assert "confidence" in result.reason


def test_restrictive_action_below_low_confidence_is_downgraded() -> None:
    result = decide_governance_action(
        evaluated_action=DecisionAction.MUTE.value,
        risk_level=RiskSeverity.MEDIUM.value,
        risk_score=0.6,
        confidence=0.50,
    )
    assert result.action == DecisionAction.REVIEW.value
    assert "downgraded" in result.reason


def test_confidence_above_threshold_keeps_restrictive_action() -> None:
    result = decide_governance_action(
        evaluated_action=DecisionAction.MUTE.value,
        risk_level=RiskSeverity.MEDIUM.value,
        risk_score=0.6,
        confidence=0.80,
    )
    assert result.action == DecisionAction.MUTE.value
    assert result.requires_review is False


def test_custom_thresholds_change_routing() -> None:
    result = decide_governance_action(
        evaluated_action=DecisionAction.BLOCK.value,
        risk_level=RiskSeverity.HIGH.value,
        risk_score=0.9,
        confidence=0.60,
        thresholds=DecisionThresholds(low_confidence=0.30, high_risk_confidence=0.50),
    )
    assert result.action == DecisionAction.BLOCK.value
    assert result.auto_executable is True


def test_priority_follows_risk_severity() -> None:
    low = decide_governance_action(
        evaluated_action=DecisionAction.ALLOW.value,
        risk_level=RiskSeverity.LOW.value,
        risk_score=0.1,
        confidence=0.9,
    )
    critical = decide_governance_action(
        evaluated_action=DecisionAction.REVIEW.value,
        risk_level=RiskSeverity.CRITICAL.value,
        risk_score=0.9,
        confidence=0.9,
    )
    assert critical.priority < low.priority


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_invalid_confidence_rejected(bad: float) -> None:
    with pytest.raises(ValueError, match="within"):
        decide_governance_action(
            evaluated_action=DecisionAction.ALLOW.value,
            risk_level=RiskSeverity.LOW.value,
            risk_score=0.1,
            confidence=bad,
        )


def test_invalid_threshold_rejected() -> None:
    with pytest.raises(ValueError):
        DecisionThresholds(low_confidence=1.5)
