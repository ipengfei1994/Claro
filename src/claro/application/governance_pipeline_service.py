from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from pydantic import ValidationError

from claro.application.enforcement_service import EnforcementService
from claro.application.governance_decision_service import GovernanceDecisionService
from claro.application.message_processing import (
    ConsumedMessage,
    HandlingResult,
    PermanentMessageError,
)
from claro.application.policy_evaluation_service import PolicyEvaluationService
from claro.application.risk_events import RISK_ASSESSED_EVENT, RiskAssessedPayload
from claro.data_access.repositories.governance_repository import (
    GovernanceRepository,
    OutboxDraft,
)
from claro.domain.enums import DecisionAction


class GovernancePipelineService:
    """Consume risk assessments and drive them through content governance.

    Upstream, Phase 03 publishes ``game.risk.assessed.v1`` once a risk result is
    committed. This service is the Phase 04 entry point: it evaluates policies,
    records a governance decision, routes unresolved cases to human review, and
    simulates enforcement for decisions that policy authorises automatically.

    Every step is idempotent. Evaluation rows are keyed by message and policy
    snapshot, decisions by a deterministic decision key, and enforcement by a
    deterministic idempotency key, so replaying the same risk event never
    duplicates a penalty.
    """

    def __init__(
        self,
        repository: GovernanceRepository,
        evaluation_service: PolicyEvaluationService,
        decision_service: GovernanceDecisionService,
        *,
        enforcement_service: EnforcementService | None = None,
        auto_enforce: bool = True,
    ) -> None:
        self._repository = repository
        self._evaluation = evaluation_service
        self._decision = decision_service
        self._enforcement = enforcement_service
        self._auto_enforce = auto_enforce
        self._logger = structlog.get_logger(__name__)

    def handle(self, message: ConsumedMessage) -> HandlingResult:
        event = message.event
        if event.event_type != RISK_ASSESSED_EVENT:
            raise PermanentMessageError(f"unexpected event type: {event.event_type}")
        try:
            payload = RiskAssessedPayload.from_json_mapping(event.payload)
        except (ValidationError, ValueError) as error:
            raise PermanentMessageError(f"invalid risk assessment payload: {error}") from error
        evaluation = self._evaluation.evaluate_message(payload.message_id)
        self._publish_evaluation(payload, evaluation)
        decision = self._decision.make_decision(evaluation)
        self._maybe_enforce(payload, evaluation, decision)
        return HandlingResult("processed" if evaluation.get("created", False) else "duplicate")

    def _publish_evaluation(self, payload: RiskAssessedPayload, evaluation: dict[str, Any]) -> None:
        if not evaluation.get("created", False):
            return
        self._repository.enqueue_event(
            OutboxDraft(
                event_type="game.governance.evaluated.v1",
                topic=self._repository.topics.evaluated,
                payload={
                    "synthetic": payload.synthetic,
                    "message_id": str(payload.message_id),
                    "evaluation_id": str(evaluation["id"]),
                    "selected_policy_id": evaluation.get("selected_policy_id"),
                    "suggested_action": evaluation.get("suggested_action"),
                    "risk_level": evaluation.get("risk_level"),
                    "risk_score": evaluation.get("risk_score"),
                    "matched_policy_count": len(evaluation.get("matched_policies", [])),
                    "evaluated_at": evaluation.get("evaluated_at"),
                },
                dedupe_key=f"evaluation:{payload.message_id}:{evaluation['id']}",
                headers={"event_version": "1", "aggregate": "policy_evaluation"},
            )
        )

    def _maybe_enforce(
        self,
        payload: RiskAssessedPayload,
        evaluation: dict[str, Any],
        decision: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not self._auto_enforce or self._enforcement is None:
            return None
        if decision.get("requires_review", True) or not decision.get("auto_executable", False):
            return None
        action = str(decision["action"])
        target_ref = str(evaluation["input_snapshot"].get("sender_ref") or "")
        if action == DecisionAction.BLOCK.value:
            target_ref = str(payload.message_id)
        if not target_ref:
            return None
        try:
            return self._enforcement.simulate_enforcement(
                decision_id=UUID(str(decision["id"])),
                action=action,
                target_ref=target_ref,
                reason=decision["decision_reason"],
                actor_ref="governance-engine",
            )
        except Exception as error:  # noqa: BLE001 - enforcement failure must not lose the event
            self._logger.warning(
                "governance_auto_enforcement_failed",
                message_id=str(payload.message_id),
                action=action,
                error=str(error),
            )
            return None
