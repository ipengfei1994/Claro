from __future__ import annotations

from dataclasses import dataclass

from claro.domain.enums import DecisionAction, GovernanceDecisionStatus, RiskSeverity

HIGH_RISK_LEVELS = {RiskSeverity.HIGH.value, RiskSeverity.CRITICAL.value}
RESTRICTIVE_ACTIONS = {
    DecisionAction.BLOCK.value,
    DecisionAction.MUTE.value,
    DecisionAction.TEMP_BAN.value,
    DecisionAction.PERM_BAN.value,
    DecisionAction.RESTRICT.value,
}
ENFORCEABLE_ACTIONS = RESTRICTIVE_ACTIONS | {DecisionAction.WARN.value}
RISK_PRIORITY = {
    RiskSeverity.CRITICAL.value: 1,
    RiskSeverity.HIGH.value: 2,
    RiskSeverity.MEDIUM.value: 3,
    RiskSeverity.LOW.value: 4,
    RiskSeverity.NORMAL.value: 5,
}


@dataclass(frozen=True, slots=True)
class DecisionThresholds:
    low_confidence: float = 0.55
    high_risk_confidence: float = 0.70

    def __post_init__(self) -> None:
        for value in (self.low_confidence, self.high_risk_confidence):
            if not 0 <= value <= 1:
                raise ValueError("decision thresholds must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class GovernanceActionDecision:
    action: str
    requires_review: bool
    decision_status: str
    reason: str
    priority: int
    original_action: str
    downgraded: bool

    @property
    def auto_executable(self) -> bool:
        return not self.requires_review


def decide_governance_action(
    *,
    evaluated_action: str,
    risk_level: str,
    risk_score: float,
    confidence: float,
    thresholds: DecisionThresholds | None = None,
) -> GovernanceActionDecision:
    if evaluated_action not in {item.value for item in DecisionAction}:
        raise ValueError(f"unknown evaluated action: {evaluated_action}")
    if risk_level not in RISK_PRIORITY:
        raise ValueError(f"unknown risk level: {risk_level}")
    if not 0 <= risk_score <= 1 or not 0 <= confidence <= 1:
        raise ValueError("risk score and confidence must be within [0, 1]")
    limits = thresholds or DecisionThresholds()
    action = evaluated_action
    reasons: list[str] = []
    if evaluated_action in RESTRICTIVE_ACTIONS and confidence < limits.low_confidence:
        action = DecisionAction.REVIEW.value
        reasons.append(
            f"restrictive action '{evaluated_action}' downgraded because confidence "
            f"{confidence:.2f} is below {limits.low_confidence:.2f}"
        )
    elif (
        risk_level in HIGH_RISK_LEVELS
        and confidence < limits.high_risk_confidence
        and evaluated_action != DecisionAction.REVIEW.value
    ):
        action = DecisionAction.REVIEW.value
        reasons.append(
            f"{risk_level} risk with confidence {confidence:.2f} below "
            f"{limits.high_risk_confidence:.2f} requires human review"
        )
    requires_review = action == DecisionAction.REVIEW.value
    if requires_review and not reasons:
        reasons.append("risk is high enough to require human review under the active policy")
    if not reasons:
        reasons.append(
            f"action '{action}' is auto-decided for {risk_level} risk with confidence "
            f"{confidence:.2f}"
        )
    return GovernanceActionDecision(
        action=action,
        requires_review=requires_review,
        decision_status=(
            GovernanceDecisionStatus.PENDING_REVIEW.value
            if requires_review
            else GovernanceDecisionStatus.AUTO_DECIDED.value
        ),
        reason="; ".join(reasons),
        priority=RISK_PRIORITY[risk_level],
        original_action=evaluated_action,
        downgraded=action != evaluated_action,
    )
