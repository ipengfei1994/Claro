"""Unit tests for the moderation workflow state machine."""

from __future__ import annotations

import pytest

from claro.domain.enums import CaseStatus, DecisionAction, ModerationAction, RiskSeverity
from claro.governance.moderation import (
    CASE_TRANSITIONS,
    CLAIMABLE_STATUSES,
    ModerationConflictError,
    ModerationWorkflowError,
    build_review_outcome,
    validate_claim,
    validate_review_action,
)


def test_pending_can_be_claimed() -> None:
    validate_claim(CaseStatus.PENDING.value, None, "reviewer.alice")


def test_claim_rejects_terminal_status() -> None:
    with pytest.raises(ModerationWorkflowError, match="cannot be claimed"):
        validate_claim(CaseStatus.FINALIZED.value, None, "reviewer.alice")


def test_claim_rejects_different_assignee() -> None:
    with pytest.raises(ModerationWorkflowError, match="already assigned"):
        validate_claim(CaseStatus.PENDING.value, "reviewer.bob", "reviewer.alice")


def test_claimable_statuses_are_explicit() -> None:
    assert CaseStatus.IN_REVIEW.value not in CLAIMABLE_STATUSES
    assert CaseStatus.SECOND_REVIEW.value in CLAIMABLE_STATUSES


@pytest.mark.parametrize(
    ("current", "action"),
    [
        (CaseStatus.PENDING.value, ModerationAction.ESCALATE.value),
        (CaseStatus.FINALIZED.value, ModerationAction.APPROVE.value),
        (CaseStatus.APPROVED.value, ModerationAction.REJECT.value),
    ],
)
def test_invalid_transition_rejected(current: str, action: str) -> None:
    with pytest.raises(ModerationWorkflowError, match="not allowed"):
        validate_review_action(
            current_status=current,
            action=action,
            reason="valid reason",
        )


def test_reason_is_mandatory() -> None:
    with pytest.raises(ModerationWorkflowError, match="reason"):
        validate_review_action(
            current_status=CaseStatus.IN_REVIEW.value,
            action=ModerationAction.REJECT.value,
            reason="  ",
        )


def test_override_requires_final_action_and_level() -> None:
    with pytest.raises(ModerationWorkflowError, match="override requires"):
        validate_review_action(
            current_status=CaseStatus.IN_REVIEW.value,
            action=ModerationAction.OVERRIDE.value,
            reason="human disagrees with system",
        )


def test_valid_override() -> None:
    validate_review_action(
        current_status=CaseStatus.IN_REVIEW.value,
        action=ModerationAction.OVERRIDE.value,
        reason="human disagrees with system",
        final_action=DecisionAction.BLOCK.value,
        final_level=RiskSeverity.HIGH.value,
    )


def test_approve_outcome_keeps_system_action() -> None:
    outcome = build_review_outcome(
        current_status=CaseStatus.IN_REVIEW.value,
        action=ModerationAction.APPROVE.value,
        reason="system decision confirmed",
        system_action=DecisionAction.WARN.value,
        system_level=RiskSeverity.MEDIUM.value,
        system_category="spam",
        final_action=None,
        final_level=None,
        final_category=None,
    )
    assert outcome.target_status == CaseStatus.APPROVED.value
    assert outcome.final_action == DecisionAction.WARN.value
    assert outcome.decision_status == "human_reviewed"


def test_reject_outcome_means_false_positive() -> None:
    outcome = build_review_outcome(
        current_status=CaseStatus.IN_REVIEW.value,
        action=ModerationAction.REJECT.value,
        reason="not a violation",
        system_action=DecisionAction.BLOCK.value,
        system_level=RiskSeverity.HIGH.value,
        system_category="fraud",
        final_action=None,
        final_level=None,
        final_category=None,
    )
    assert outcome.final_action == DecisionAction.ALLOW.value
    assert outcome.target_status == CaseStatus.REJECTED.value


def test_override_outcome_uses_human_values() -> None:
    outcome = build_review_outcome(
        current_status=CaseStatus.IN_REVIEW.value,
        action=ModerationAction.OVERRIDE.value,
        reason="evidence supports a stricter action",
        system_action=DecisionAction.WARN.value,
        system_level=RiskSeverity.MEDIUM.value,
        system_category="spam",
        final_action=DecisionAction.TEMP_BAN.value,
        final_level=RiskSeverity.HIGH.value,
        final_category="fraud",
    )
    assert outcome.final_action == DecisionAction.TEMP_BAN.value
    assert outcome.final_level == RiskSeverity.HIGH.value
    assert outcome.final_category == "fraud"
    assert outcome.decision_status == "overridden"


def test_second_review_transition() -> None:
    outcome = build_review_outcome(
        current_status=CaseStatus.IN_REVIEW.value,
        action=ModerationAction.REQUEST_SECOND_REVIEW.value,
        reason="needs senior review",
        system_action=DecisionAction.REVIEW.value,
        system_level=None,
        system_category=None,
        final_action=None,
        final_level=None,
        final_category=None,
    )
    assert outcome.target_status == CaseStatus.SECOND_REVIEW.value
    assert outcome.requires_second_review is True


def test_reopen_from_terminal_status() -> None:
    validate_review_action(
        current_status=CaseStatus.FINALIZED.value,
        action=ModerationAction.REOPEN.value,
        reason="new evidence submitted",
    )


def test_terminal_statuses_can_reopen_but_not_advance_directly() -> None:
    for status in (
        CaseStatus.APPROVED.value,
        CaseStatus.REJECTED.value,
        CaseStatus.FINALIZED.value,
    ):
        assert CASE_TRANSITIONS[status] == frozenset({CaseStatus.IN_REVIEW.value})


def test_conflict_error_is_distinct_type() -> None:
    assert issubclass(ModerationConflictError, RuntimeError)
