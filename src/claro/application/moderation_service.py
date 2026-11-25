from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from claro.application.feedback_audit_service import FeedbackAuditService
from claro.data_access.repositories.governance_repository import (
    GovernanceRepository,
    GovernanceValidationError,
)
from claro.domain.enums import CaseStatus, ModerationAction
from claro.governance.moderation import ModerationConflictError, ModerationWorkflowError

SENIOR_ROLES = frozenset({"senior_moderator", "admin"})
KNOWN_ROLES = frozenset({"moderator", "senior_moderator", "admin", "auditor"})
_OPEN_STATUSES = (
    CaseStatus.PENDING.value,
    CaseStatus.IN_REVIEW.value,
    CaseStatus.ESCALATED.value,
    CaseStatus.SECOND_REVIEW.value,
)
_SECOND_REVIEW_ACTIONS = frozenset(
    {ModerationAction.APPROVE.value, ModerationAction.REJECT.value, ModerationAction.OVERRIDE.value}
)


class ModerationService:
    """Human moderation workbench: queue, claim, review and second review.

    Role checks and separation of duties are simulated: single-machine demos
    switch reviewer identity manually. This is explicitly *not* production
    authentication and is labelled as simulated in the interface.
    """

    def __init__(
        self,
        repository: GovernanceRepository,
        *,
        feedback_service: FeedbackAuditService | None = None,
    ) -> None:
        self._repository = repository
        self._feedback = feedback_service
        self._logger = structlog.get_logger(__name__)

    # Queue ------------------------------------------------------------------
    def queue(
        self,
        *,
        statuses: list[str] | None = None,
        assignee: str | None = None,
        risk_level: str | None = None,
        overdue: bool = False,
        search: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        return self._repository.list_cases(
            statuses=statuses,
            assignee=assignee,
            risk_level=risk_level,
            overdue=overdue,
            search=search,
            limit=limit,
        )

    def open_queue(self, *, limit: int = 200) -> list[dict[str, Any]]:
        return self._repository.list_cases(statuses=list(_OPEN_STATUSES), limit=limit)

    def detail(self, case_id: UUID) -> dict[str, Any]:
        return self._repository.case_detail(case_id)

    def review_history(self, case_id: UUID) -> list[dict[str, Any]]:
        return self._repository.list_reviews(case_id)

    def case_events(self, case_id: UUID) -> list[dict[str, Any]]:
        return self._repository.case_events(case_id)

    # Actions ----------------------------------------------------------------
    def claim(
        self,
        case_id: UUID,
        *,
        reviewer_ref: str,
        reviewer_role: str,
        expected_lock_version: int | None = None,
    ) -> dict[str, Any]:
        self._validate_role(reviewer_role)
        return self._repository.claim_case(
            case_id,
            reviewer_ref=reviewer_ref,
            reviewer_role=reviewer_role,
            expected_lock_version=expected_lock_version,
        )

    def submit_review(
        self,
        case_id: UUID,
        *,
        reviewer_ref: str,
        reviewer_role: str,
        action: str,
        reason: str,
        final_action: str | None = None,
        final_level: str | None = None,
        final_category: str | None = None,
        notes: str | None = None,
        expected_lock_version: int | None = None,
        feedback_type: str | None = None,
        feedback_difference_reason: str | None = None,
    ) -> dict[str, Any]:
        self._validate_role(reviewer_role)
        if action not in {item.value for item in ModerationAction}:
            raise GovernanceValidationError(f"unknown moderation action: {action}")
        if not isinstance(reason, str) or len(reason.strip()) < 3:
            raise GovernanceValidationError("a review reason of at least 3 characters is required")
        if action in {
            ModerationAction.ESCALATE.value,
            ModerationAction.REQUEST_SECOND_REVIEW.value,
        }:
            if reviewer_role not in SENIOR_ROLES:
                raise GovernanceValidationError(
                    f"action '{action}' requires a senior moderator or admin role"
                )
        detail = self._repository.case_detail(case_id)
        current_status = str(detail["case"]["status"])
        if current_status == CaseStatus.SECOND_REVIEW.value and action in _SECOND_REVIEW_ACTIONS:
            requester = self._second_review_requester(case_id)
            if requester is not None and requester == reviewer_ref:
                raise ModerationConflictError(
                    "a second review must be completed by a different reviewer than the requester"
                )
        try:
            result = self._repository.review_case(
                case_id,
                reviewer_ref=reviewer_ref,
                reviewer_role=reviewer_role,
                action=action,
                reason=reason,
                final_action=final_action,
                final_level=final_level,
                final_category=final_category,
                notes=notes,
                expected_lock_version=expected_lock_version,
            )
        except ModerationWorkflowError as error:
            raise GovernanceValidationError(str(error)) from error
        if feedback_type and self._feedback is not None:
            result["feedback"] = self._feedback.submit_feedback(
                message_id=UUID(str(detail["case"]["message_id"])),
                decision_id=(
                    UUID(str(detail["decision"]["id"])) if detail.get("decision") else None
                ),
                review_id=UUID(str(result["review"]["id"])),
                feedback_type=feedback_type,
                difference_reason=(feedback_difference_reason or reason),
                final_risk={
                    "final_action": result.get("final_action"),
                    "final_level": result.get("final_level"),
                    "final_category": result.get("final_category"),
                },
                reviewer_ref=reviewer_ref,
                is_synthetic=bool(detail["case"].get("is_synthetic", True)),
            )
        return result

    def escalate(
        self,
        case_id: UUID,
        *,
        reviewer_ref: str,
        reviewer_role: str,
        reason: str,
        notes: str | None = None,
        expected_lock_version: int | None = None,
    ) -> dict[str, Any]:
        return self.submit_review(
            case_id,
            reviewer_ref=reviewer_ref,
            reviewer_role=reviewer_role,
            action=ModerationAction.ESCALATE.value,
            reason=reason,
            notes=notes,
            expected_lock_version=expected_lock_version,
        )

    def request_second_review(
        self,
        case_id: UUID,
        *,
        reviewer_ref: str,
        reviewer_role: str,
        reason: str,
        notes: str | None = None,
        expected_lock_version: int | None = None,
    ) -> dict[str, Any]:
        return self.submit_review(
            case_id,
            reviewer_ref=reviewer_ref,
            reviewer_role=reviewer_role,
            action=ModerationAction.REQUEST_SECOND_REVIEW.value,
            reason=reason,
            notes=notes,
            expected_lock_version=expected_lock_version,
        )

    def reopen(
        self,
        case_id: UUID,
        *,
        reviewer_ref: str,
        reviewer_role: str,
        reason: str,
        expected_lock_version: int | None = None,
    ) -> dict[str, Any]:
        return self.submit_review(
            case_id,
            reviewer_ref=reviewer_ref,
            reviewer_role=reviewer_role,
            action=ModerationAction.REOPEN.value,
            reason=reason,
            expected_lock_version=expected_lock_version,
        )

    # Helpers ----------------------------------------------------------------
    def _second_review_requester(self, case_id: UUID) -> str | None:
        history = self._repository.list_reviews(case_id)
        for review in reversed(history):
            if review["action"] == ModerationAction.REQUEST_SECOND_REVIEW.value:
                return str(review["reviewer_ref"])
        return None

    @staticmethod
    def _validate_role(reviewer_role: str) -> None:
        if reviewer_role not in KNOWN_ROLES:
            raise GovernanceValidationError(
                f"unknown reviewer role '{reviewer_role}'; expected one of {sorted(KNOWN_ROLES)}"
            )

    @staticmethod
    def roles() -> list[dict[str, str]]:
        return [
            {"role": "moderator", "label": "审核员 (模拟)"},
            {"role": "senior_moderator", "label": "高级审核员 (模拟)"},
            {"role": "admin", "label": "管理员 (模拟)"},
            {"role": "auditor", "label": "审计员 (模拟)"},
        ]
