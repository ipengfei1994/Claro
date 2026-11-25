from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog

from claro.data_access.repositories.governance_repository import (
    CaseDraft,
    GovernanceNotFoundError,
    GovernanceRepository,
    GovernanceValidationError,
    OutboxDraft,
)
from claro.domain.enums import CaseStatus, DecisionAction, GovernanceDecisionStatus, RiskSeverity
from claro.governance.decision import (
    ENFORCEABLE_ACTIONS,
    DecisionThresholds,
    GovernanceActionDecision,
    decide_governance_action,
)

_HIGH_RISK = {RiskSeverity.HIGH.value, RiskSeverity.CRITICAL.value}


class GovernanceDecisionService:
    """Turn a policy evaluation into a governance decision.

    Risk severity and model confidence are handled separately: a restrictive
    action is never auto-executed when confidence is low, and high or critical
    risk with weak evidence is always routed to human review.
    """

    def __init__(
        self,
        repository: GovernanceRepository,
        *,
        thresholds: DecisionThresholds | None = None,
        review_sla_hours: int = 24,
        decided_by: str = "governance-engine",
    ) -> None:
        if review_sla_hours < 1:
            raise ValueError("review_sla_hours must be positive")
        self._repository = repository
        self._thresholds = thresholds or DecisionThresholds()
        self._review_sla_hours = review_sla_hours
        self._decided_by = decided_by
        self._logger = structlog.get_logger(__name__)

    def make_decision(
        self, evaluation: dict[str, Any], *, now: datetime | None = None
    ) -> dict[str, Any]:
        moment = now or datetime.now(UTC)
        message_id = UUID(str(evaluation["message_id"]))
        risk_score = float(evaluation["risk_score"])
        risk_level = str(evaluation["risk_level"])
        confidence = float(evaluation["input_snapshot"].get("confidence", 0.0) or 0.0)
        evaluated_action = str(evaluation["suggested_action"])
        selected_policy_id = evaluation.get("selected_policy_id")
        if not selected_policy_id:
            raise GovernanceValidationError(
                "evaluation has no selected policy; ensure the default policy exists"
            )
        decision: GovernanceActionDecision = decide_governance_action(
            evaluated_action=evaluated_action,
            risk_level=risk_level,
            risk_score=risk_score,
            confidence=confidence,
            thresholds=self._thresholds,
        )
        decision_key = f"gov:{message_id}:{evaluation['id']}"
        requires_review = decision.requires_review
        case_draft = (
            self._case_draft(evaluation, decision, risk_level, risk_score, moment)
            if requires_review
            else None
        )
        explanation = self._explain(
            evaluation=evaluation,
            decision=decision,
            confidence=confidence,
            requires_review=requires_review,
        )
        resolved = self._repository.create_decision(
            message_id=message_id,
            dataset_id=(
                UUID(str(evaluation["dataset_id"])) if evaluation.get("dataset_id") else None
            ),
            policy_id=UUID(str(selected_policy_id)),
            action=decision.action,
            risk_score=risk_score,
            risk_level=risk_level,
            confidence=confidence,
            decision_key=decision_key,
            decision_status=decision.decision_status,
            decision_reason=decision.reason,
            requires_review=requires_review,
            priority=decision.priority,
            risk_result_id=(
                UUID(str(evaluation["risk_result_id"]))
                if evaluation.get("risk_result_id")
                else None
            ),
            policy_evaluation_id=UUID(str(evaluation["id"])),
            decided_by=self._decided_by,
            explanation=explanation,
            is_synthetic=bool(evaluation.get("is_synthetic", True)),
            case_draft=case_draft,
            outbox=OutboxDraft(
                event_type="game.governance.decided.v1",
                topic=self._repository.topics.decision,
                payload={
                    "synthetic": bool(evaluation.get("is_synthetic", True)),
                    "message_id": str(message_id),
                    "policy_evaluation_id": str(evaluation["id"]),
                    "action": decision.action,
                    "decision_status": decision.decision_status,
                    "risk_level": risk_level,
                    "risk_score": risk_score,
                    "confidence": confidence,
                    "requires_review": requires_review,
                    "original_action": decision.original_action,
                    "downgraded": decision.downgraded,
                },
                dedupe_key=f"decision:{decision_key}",
                headers={"event_version": "1", "aggregate": "policy_decision"},
            ),
        )
        return {
            **resolved,
            "explanation": explanation,
            "auto_executable": decision.auto_executable and decision.action in ENFORCEABLE_ACTIONS,
            "downgraded": decision.downgraded,
            "original_action": decision.original_action,
        }

    def list_decisions(
        self,
        *,
        status: str | None = None,
        action: str | None = None,
        requires_review: bool | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        return self._repository.list_decisions(
            status=status,
            action=action,
            requires_review=requires_review,
            limit=limit,
        )

    def explain_decision(self, decision_id: UUID) -> dict[str, Any]:
        decision = self._repository.get_decision(decision_id)
        if decision is None:
            raise GovernanceNotFoundError(f"decision not found: {decision_id}")
        explanation = decision.get("explanation") or {}
        return {
            "decision": decision,
            "action": decision["action"],
            "decision_status": decision["decision_status"],
            "decision_reason": decision["decision_reason"],
            "requires_review": decision["requires_review"],
            "confidence": decision["confidence"],
            "priority": decision["priority"],
            "risk_level": (decision["reason_codes"] or [None, None])[1],
            "evidence": explanation.get("evidence", {}),
            "policy": explanation.get("policy", {}),
            "alternatives": explanation.get("alternatives", []),
            "review_trigger": explanation.get("review_trigger"),
            "human_review": explanation.get("human_review"),
        }

    def override_decision(
        self,
        decision_id: UUID,
        *,
        actor_ref: str,
        reason: str,
        action: str | None = None,
        status: str = GovernanceDecisionStatus.OVERRIDDEN.value,
    ) -> dict[str, Any]:
        if not isinstance(reason, str) or len(reason.strip()) < 3:
            raise GovernanceValidationError(
                "an override reason of at least 3 characters is required"
            )
        if status not in {item.value for item in GovernanceDecisionStatus}:
            raise GovernanceValidationError(f"unknown decision status: {status}")
        if action is not None and action not in {item.value for item in DecisionAction}:
            raise GovernanceValidationError(f"unknown decision action: {action}")
        existing = self._repository.get_decision(decision_id)
        if existing is None:
            raise GovernanceNotFoundError(f"decision not found: {decision_id}")
        result = self._repository.update_decision_status(
            decision_id, status=status, actor_ref=actor_ref, reason=reason
        )
        return {**result, "requested_action": action}

    def _case_draft(
        self,
        evaluation: dict[str, Any],
        decision: GovernanceActionDecision,
        risk_level: str,
        risk_score: float,
        moment: datetime,
    ) -> CaseDraft:
        snapshot = {
            "risk_level": risk_level,
            "risk_score": risk_score,
            "confidence": float(evaluation["input_snapshot"].get("confidence", 0.0) or 0.0),
            "suggested_action": decision.action,
            "original_action": decision.original_action,
            "risk_result_id": evaluation.get("risk_result_id"),
            "categories": list(evaluation["input_snapshot"].get("categories", [])),
            "matched_policies": [item.get("policy_key") for item in evaluation["matched_policies"]],
        }
        return CaseDraft(
            status=CaseStatus.PENDING.value,
            priority=decision.priority,
            required_second_review=risk_level in _HIGH_RISK,
            due_at=moment + timedelta(hours=self._review_sla_hours),
            risk_snapshot=snapshot,
        )

    def _explain(
        self,
        *,
        evaluation: dict[str, Any],
        decision: GovernanceActionDecision,
        confidence: float,
        requires_review: bool,
    ) -> dict[str, Any]:
        alternatives: list[dict[str, Any]] = []
        if decision.downgraded:
            alternatives.append(
                {
                    "action": decision.original_action,
                    "rejected_because": (
                        "policy suggested a restrictive action but confidence was below the "
                        "automatic-execution threshold"
                    ),
                }
            )
        matched = evaluation.get("matched_policies", [])
        alternatives.extend(
            {
                "action": item.get("action"),
                "policy_key": item.get("policy_key"),
                "rejected_because": "a higher-ranked policy produced the final action",
            }
            for item in matched[1:]
        )
        return {
            "policy": {
                "selected_policy_id": evaluation.get("selected_policy_id"),
                "selected_policy_version": evaluation.get("selected_policy_version"),
                "evaluation_id": evaluation["id"],
                "evaluation_reason": evaluation.get("evaluation_reason"),
                "matched_policy_count": len(matched),
                "conflicts": list(evaluation.get("conflicts", [])),
            },
            "evidence": {
                "risk_score": evaluation["risk_score"],
                "risk_level": evaluation["risk_level"],
                "confidence": confidence,
                "thresholds": {
                    "low_confidence": self._thresholds.low_confidence,
                    "high_risk_confidence": self._thresholds.high_risk_confidence,
                },
            },
            "review_trigger": (decision.reason if requires_review else None),
            "confidence_split": {
                "severity": evaluation["risk_level"],
                "confidence": confidence,
                "severity_high_confidence_low": requires_review
                and evaluation["risk_level"] in _HIGH_RISK,
            },
            "alternatives": alternatives,
        }
