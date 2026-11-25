from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from claro.domain.enums import (
    CaseStatus,
    DecisionAction,
    ModerationAction,
    RiskSeverity,
)

TERMINAL_STATUSES = {
    CaseStatus.APPROVED.value,
    CaseStatus.REJECTED.value,
    CaseStatus.FINALIZED.value,
}
FINAL_DECISION_STATUS = {
    ModerationAction.APPROVE: "human_reviewed",
    ModerationAction.REJECT: "human_reviewed",
    ModerationAction.OVERRIDE: "overridden",
}

CASE_TRANSITIONS: Mapping[str, frozenset[str]] = {
    CaseStatus.PENDING.value: frozenset({CaseStatus.IN_REVIEW.value}),
    CaseStatus.OPEN.value: frozenset({CaseStatus.IN_REVIEW.value}),
    CaseStatus.IN_REVIEW.value: frozenset(
        {
            CaseStatus.APPROVED.value,
            CaseStatus.REJECTED.value,
            CaseStatus.ESCALATED.value,
            CaseStatus.SECOND_REVIEW.value,
            CaseStatus.FINALIZED.value,
        }
    ),
    CaseStatus.ESCALATED.value: frozenset(
        {
            CaseStatus.IN_REVIEW.value,
            CaseStatus.SECOND_REVIEW.value,
            CaseStatus.FINALIZED.value,
            CaseStatus.REJECTED.value,
        }
    ),
    CaseStatus.SECOND_REVIEW.value: frozenset(
        {
            CaseStatus.APPROVED.value,
            CaseStatus.REJECTED.value,
            CaseStatus.FINALIZED.value,
            CaseStatus.IN_REVIEW.value,
        }
    ),
    CaseStatus.APPROVED.value: frozenset({CaseStatus.IN_REVIEW.value}),
    CaseStatus.REJECTED.value: frozenset({CaseStatus.IN_REVIEW.value}),
    CaseStatus.FINALIZED.value: frozenset({CaseStatus.IN_REVIEW.value}),
    CaseStatus.RESOLVED.value: frozenset({CaseStatus.IN_REVIEW.value}),
}

ACTION_TARGET: Mapping[str, str] = {
    ModerationAction.APPROVE.value: CaseStatus.APPROVED.value,
    ModerationAction.REJECT.value: CaseStatus.REJECTED.value,
    ModerationAction.OVERRIDE.value: CaseStatus.FINALIZED.value,
    ModerationAction.ESCALATE.value: CaseStatus.ESCALATED.value,
    ModerationAction.REQUEST_SECOND_REVIEW.value: CaseStatus.SECOND_REVIEW.value,
    ModerationAction.REOPEN.value: CaseStatus.IN_REVIEW.value,
}

CLAIMABLE_STATUSES = {
    CaseStatus.PENDING.value,
    CaseStatus.OPEN.value,
    CaseStatus.ESCALATED.value,
    CaseStatus.SECOND_REVIEW.value,
}


class ModerationWorkflowError(ValueError):
    pass


class ModerationConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    target_status: str
    decision_status: str | None
    final_action: str
    final_level: str | None
    final_category: str | None
    requires_second_review: bool


def validate_claim(status: str, assignee_ref: str | None, actor_ref: str) -> None:
    if status not in CLAIMABLE_STATUSES:
        raise ModerationWorkflowError(f"case status '{status}' cannot be claimed")
    if assignee_ref is not None and assignee_ref != actor_ref:
        raise ModerationWorkflowError(
            f"case is already assigned to {assignee_ref}; only the assignee may claim it"
        )


def validate_review_action(
    *,
    current_status: str,
    action: str,
    reason: str,
    final_action: str | None = None,
    final_level: str | None = None,
    final_category: str | None = None,
) -> None:
    if action not in {item.value for item in ModerationAction}:
        raise ModerationWorkflowError(f"unknown moderation action: {action}")
    if not isinstance(reason, str) or len(reason.strip()) < 3:
        raise ModerationWorkflowError("a review reason of at least 3 characters is required")
    target = ACTION_TARGET[action]
    allowed = CASE_TRANSITIONS.get(current_status, frozenset())
    if target not in allowed:
        raise ModerationWorkflowError(
            f"transition from '{current_status}' to '{target}' via '{action}' is not allowed"
        )
    if action == ModerationAction.OVERRIDE.value:
        if final_action is None or final_level is None:
            raise ModerationWorkflowError("override requires final_action and final_level")
    if final_action is not None and final_action not in {item.value for item in DecisionAction}:
        raise ModerationWorkflowError(f"unknown final action: {final_action}")
    if final_level is not None and final_level not in {item.value for item in RiskSeverity}:
        raise ModerationWorkflowError(f"unknown final risk level: {final_level}")
    if final_category is not None and not final_category.strip():
        raise ModerationWorkflowError("final_category must not be blank when provided")


def build_review_outcome(
    *,
    current_status: str,
    action: str,
    reason: str,
    system_action: str,
    system_level: str | None,
    system_category: str | None,
    final_action: str | None,
    final_level: str | None,
    final_category: str | None,
) -> ReviewOutcome:
    validate_review_action(
        current_status=current_status,
        action=action,
        reason=reason,
        final_action=final_action,
        final_level=final_level,
        final_category=final_category,
    )
    target = ACTION_TARGET[action]
    if action == ModerationAction.REJECT.value:
        resolved_action = DecisionAction.ALLOW.value
    else:
        resolved_action = final_action or system_action
    return ReviewOutcome(
        target_status=target,
        decision_status=FINAL_DECISION_STATUS.get(ModerationAction(action)),
        final_action=resolved_action,
        final_level=final_level or system_level,
        final_category=final_category or system_category,
        requires_second_review=action == ModerationAction.REQUEST_SECOND_REVIEW.value,
    )
