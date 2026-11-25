"""Integration tests: governance lifecycle against real PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select

from claro.bootstrap import AppContainer
from claro.data_access.models import (
    AuditEvent,
    EnforcementAction,
    GovernanceFeedback,
    ModerationCase,
    ModerationReview,
    OutboxEvent,
    PolicyEvaluation,
    PolicyVersion,
)
from claro.domain.enums import (
    CaseStatus,
    DecisionAction,
    FeedbackType,
    GovernanceDecisionStatus,
    PolicyType,
    RiskSeverity,
)


def _count(session, model, **filters) -> int:
    statement = select(func.count()).select_from(model)
    for key, value in filters.items():
        statement = statement.where(getattr(model, key) == value)
    return int(session.scalar(statement) or 0)


@pytest.mark.integration
def test_policy_lifecycle_versioning_rollback_on_postgresql(
    full_container: AppContainer, governance_data: dict
) -> None:
    service = full_container.policy_service
    prefix = governance_data["policy_prefix"]
    created = service.create_policy(
        policy_key=f"{prefix}keyword",
        name="集成测试关键词策略",
        description="synthetic integration policy",
        policy_type=PolicyType.KEYWORD.value,
        target_scope={},
        conditions={"field": "content", "op": "contains", "value": "免费"},
        action=DecisionAction.WARN.value,
        priority=60,
        created_by="it.reviewer",
        change_reason="initial version",
    )
    policy_id = UUID(str(created["id"]))
    assert created["version"] == 1

    updated = service.update_policy(
        policy_id,
        actor_ref="it.reviewer",
        reason="increase severity",
        action=DecisionAction.BLOCK.value,
        priority=70,
    )
    assert updated["version"] == 2
    assert updated["action"] == DecisionAction.BLOCK.value

    versions = service.versions(policy_id)
    assert [item["version"] for item in versions] == [1, 2]

    compared = service.compare_versions(policy_id, 1, 2)
    assert compared["changed"] and compared["identical"] is False

    rolled = service.rollback_policy(
        policy_id, target_version=1, actor_ref="it.admin", reason="rollback after review"
    )
    assert rolled["version"] == 3
    assert rolled["action"] == DecisionAction.WARN.value
    assert len(service.versions(policy_id)) == 3

    disabled = service.set_enabled(
        policy_id, enabled=False, actor_ref="it.admin", reason="temporary disable"
    )
    assert disabled["enabled"] is False

    with full_container.session_factory() as session:
        assert _count(session, PolicyVersion, policy_id=policy_id) == 4
        assert _count(session, AuditEvent, entity_id=policy_id) >= 4


@pytest.mark.integration
def test_evaluation_and_decision_persist_with_ids_and_outbox(
    full_container: AppContainer, governance_data: dict
) -> None:
    message_id = UUID(str(governance_data["message_id"]))
    evaluation = full_container.policy_evaluation_service.evaluate_message(message_id)
    assert evaluation["created"] is True
    evaluation_id = UUID(str(evaluation["id"]))
    assert evaluation["selected_policy_id"]

    decision = full_container.governance_decision_service.make_decision(evaluation)
    decision_id = UUID(str(decision["id"]))
    assert decision["decision_key"] == f"gov:{message_id}:{evaluation_id}"
    assert decision["explanation"]["alternatives"] is not None
    explained = full_container.governance_decision_service.explain_decision(decision_id)
    assert explained["action"] == decision["action"]

    with full_container.session_factory() as session:
        assert _count(session, PolicyEvaluation, message_id=message_id) == 1
        # Evaluation outbox events are enqueued by GovernancePipelineService, not by
        # the evaluation service itself; decision events are enqueued on decision.
        assert (
            _count(session, OutboxEvent, dedupe_key=f"decision:gov:{message_id}:{evaluation_id}")
            == 1
        )

    duplicate = full_container.policy_evaluation_service.evaluate_message(message_id)
    assert duplicate["created"] is False
    assert duplicate["id"] == evaluation["id"]
    duplicate_decision = full_container.governance_decision_service.make_decision(duplicate)
    assert duplicate_decision["id"] == decision["id"]
    with full_container.session_factory() as session:
        assert _count(session, PolicyEvaluation, message_id=message_id) == 1


@pytest.mark.integration
def test_policy_change_changes_decision_for_same_message(
    full_container: AppContainer, governance_data: dict
) -> None:
    """A policy edit must produce a new evaluation and a different real decision."""
    message_id = UUID(str(governance_data["message_id"]))
    first_evaluation = full_container.policy_evaluation_service.evaluate_message(message_id)
    first_decision = full_container.governance_decision_service.make_decision(first_evaluation)
    original_action = str(first_decision["action"])
    target_action = (
        DecisionAction.ALLOW.value
        if original_action != DecisionAction.ALLOW.value
        else DecisionAction.BLOCK.value
    )

    created = full_container.policy_service.create_policy(
        policy_key=f"{governance_data['policy_prefix']}switch",
        name="集成测试策略切换",
        description="synthetic acceptance policy switch",
        policy_type=PolicyType.KEYWORD.value,
        target_scope={"players": [governance_data["sender_ref"]]},
        conditions={"field": "content", "op": "contains", "value": "免费"},
        action=target_action,
        priority=1_000,
        emergency=True,
        created_by="it.reviewer",
        change_reason="acceptance: policy change must alter decision",
    )

    second_evaluation = full_container.policy_evaluation_service.evaluate_message(message_id)
    second_decision = full_container.governance_decision_service.make_decision(second_evaluation)

    assert second_evaluation["created"] is True
    assert second_evaluation["id"] != first_evaluation["id"]
    assert second_decision["id"] != first_decision["id"]
    assert second_decision["action"] == target_action
    assert second_decision["action"] != original_action
    assert second_evaluation["selected_policy_id"] == str(created["id"])
    assert (
        second_decision["explanation"]["policy"]["selected_policy_id"] == str(created["id"])
    )


@pytest.mark.integration
def test_decision_override_creates_review_linked_to_original_risk(
    full_container: AppContainer, governance_data: dict
) -> None:
    """A human override must be reviewable and trace back to the original risk."""
    message_id = UUID(str(governance_data["message_id"]))
    evaluation = full_container.policy_evaluation_service.evaluate_message(message_id)
    decision = full_container.governance_decision_service.make_decision(evaluation)
    decision_id = UUID(str(decision["id"]))

    overridden = full_container.governance_decision_service.override_decision(
        decision_id,
        actor_ref="it.admin",
        actor_role="admin",
        reason="human corrected the automated decision",
        action=DecisionAction.WARN.value,
    )
    review_id = UUID(str(overridden["review_id"]))
    assert overridden["decision_status"] == GovernanceDecisionStatus.OVERRIDDEN.value
    assert overridden["case_id"]
    assert overridden["final_action"] == DecisionAction.WARN.value

    trace = full_container.feedback_audit_service.trace(message_id)
    assert any(item["id"] == str(review_id) for item in trace["reviews"])
    assert trace["case"]["status"] == "finalized"

    feedback = full_container.feedback_audit_service.submit_feedback(
        message_id=message_id,
        decision_id=decision_id,
        review_id=review_id,
        feedback_type=FeedbackType.FALSE_POSITIVE.value,
        difference_reason="benign content misclassified",
        reviewer_ref="it.admin",
    )
    assert feedback["review_id"] == str(review_id)
    assert feedback["original_prediction"]["risk_result_id"] == str(
        governance_data["risk_result_id"]
    )
    assert feedback["original_risk"]["risk_score"] is not None
    assert feedback["policy_version"] is not None

    with full_container.session_factory() as session:
        stored = session.get(GovernanceFeedback, UUID(str(feedback["id"])))
        assert stored is not None
        assert stored.review_id == review_id
        assert stored.decision_id == decision_id


@pytest.mark.integration
def test_enforcement_events_carry_full_governance_trace(
    full_container: AppContainer, governance_data: dict
) -> None:
    """Every simulated enforcement must carry decision/policy/review/risk links."""
    message_id = UUID(str(governance_data["message_id"]))
    prefix = governance_data["policy_prefix"]
    full_container.policy_service.create_policy(
        policy_key=f"{prefix}trace-review",
        name="集成测试追溯审核策略",
        description="synthetic traceability review policy",
        policy_type=PolicyType.KEYWORD.value,
        target_scope={"players": [governance_data["sender_ref"]]},
        conditions={"field": "content", "op": "contains", "value": "免费"},
        action=DecisionAction.REVIEW.value,
        priority=1_000,
        emergency=True,
        created_by="it.reviewer",
        change_reason="force reviewed enforcement path",
    )
    evaluation = full_container.policy_evaluation_service.evaluate_message(message_id)
    decision = full_container.governance_decision_service.make_decision(evaluation)
    decision_id = UUID(str(decision["id"]))
    case_id = UUID(str(decision["case_id"]))

    moderation = full_container.moderation_service
    moderation.claim(
        case_id,
        reviewer_ref="it.reviewer.alice",
        reviewer_role="moderator",
    )
    reviewed = moderation.submit_review(
        case_id,
        reviewer_ref="it.reviewer.alice",
        reviewer_role="moderator",
        action="override",
        reason="reviewed and reduced to simulated mute",
        final_action=DecisionAction.MUTE.value,
        final_level=RiskSeverity.HIGH.value,
    )
    review_id = UUID(str(reviewed["review"]["id"]))

    enforced = full_container.enforcement_service.simulate_enforcement(
        decision_id=decision_id,
        action=DecisionAction.MUTE.value,
        target_ref=governance_data["sender_ref"],
        reason="integration test traceability",
        actor_ref="governance-engine",
        duration_seconds=60,
    )
    enforcement_id = UUID(str(enforced["id"]))
    trace = (enforced.get("details") or {}).get("trace") or {}
    expected = {
        "message_id": str(message_id),
        "decision_id": str(decision_id),
        "case_id": str(case_id),
        "review_id": str(review_id),
        "policy_id": str(decision["policy_id"]),
        "risk_result_id": str(governance_data["risk_result_id"]),
    }
    for key, value in expected.items():
        assert trace.get(key) == value
    assert trace.get("policy_version") is not None

    with full_container.session_factory() as session:
        executed = session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.dedupe_key == f"enforcement.executed:{enforcement_id}"
            )
        )
        assert executed is not None
        for key, value in expected.items():
            assert executed.payload.get(key) == value
        assert executed.payload.get("simulated_only") is True
        row = session.get(EnforcementAction, enforcement_id)
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    assert full_container.governance_repository.expire_due_enforcements() >= 1

    with full_container.session_factory() as session:
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.entity_id == enforcement_id,
                AuditEvent.action == "enforcement.expired",
            )
        )
        assert audit is not None
        expired = session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.dedupe_key == f"enforcement.expired:{enforcement_id}"
            )
        )
        assert expired is not None
        assert expired.payload.get("review_id") == str(review_id)
        assert expired.payload.get("policy_id") == str(decision["policy_id"])
        assert expired.payload.get("simulated_only") is True
        session.execute(delete(AuditEvent).where(AuditEvent.entity_id == enforcement_id))


@pytest.mark.integration
def test_review_workflow_with_optimistic_lock_on_postgresql(
    full_container: AppContainer, governance_data: dict
) -> None:
    prefix = governance_data["policy_prefix"]
    full_container.policy_service.create_policy(
        policy_key=f"{prefix}review",
        name="集成测试审核策略",
        description="synthetic forced review policy",
        policy_type=PolicyType.KEYWORD.value,
        target_scope={"players": [governance_data["sender_ref"]]},
        conditions={"field": "content", "op": "contains", "value": "免费"},
        action=DecisionAction.REVIEW.value,
        priority=1000,
        emergency=True,
        created_by="it.reviewer",
        change_reason="force review path",
    )
    evaluation = full_container.policy_evaluation_service.evaluate_message(
        UUID(str(governance_data["message_id"]))
    )
    decision = full_container.governance_decision_service.make_decision(evaluation)
    case_id = decision.get("case_id")
    assert case_id, "policy-driven REVIEW should create a review case"
    case_uuid = UUID(str(case_id))
    service = full_container.moderation_service

    claimed = service.claim(
        case_uuid,
        reviewer_ref="it.reviewer.alice",
        reviewer_role="moderator",
    )
    assert claimed["status"] == CaseStatus.IN_REVIEW.value

    from claro.governance.moderation import ModerationWorkflowError

    with pytest.raises(ModerationWorkflowError):
        service.claim(
            case_uuid,
            reviewer_ref="it.reviewer.bob",
            reviewer_role="moderator",
            expected_lock_version=claimed["lock_version"],
        )

    submitted = service.submit_review(
        case_uuid,
        reviewer_ref="it.reviewer.alice",
        reviewer_role="moderator",
        action="reject",
        reason="false positive: content is benign",
        expected_lock_version=claimed["lock_version"],
        feedback_type=FeedbackType.FALSE_POSITIVE.value,
        feedback_difference_reason="rule matched promotional word in benign context",
    )
    assert submitted["status"] == CaseStatus.REJECTED.value
    assert submitted["feedback"]["is_error_case"] is True

    with full_container.session_factory() as session:
        assert _count(session, ModerationReview, case_id=case_uuid) == 1
        assert _count(session, GovernanceFeedback, message_id=governance_data["message_id"]) == 1
        stored_case = session.get(ModerationCase, case_uuid)
        assert stored_case is not None
        assert stored_case.status == CaseStatus.REJECTED.value

    reopened = service.reopen(
        case_uuid,
        reviewer_ref="it.reviewer.alice",
        reviewer_role="moderator",
        reason="new evidence arrived",
    )
    assert reopened["status"] == CaseStatus.IN_REVIEW.value
    with full_container.session_factory() as session:
        assert _count(session, ModerationReview, case_id=case_uuid) == 2


@pytest.mark.integration
def test_enforcement_simulation_state_expiry_release_on_postgresql(
    full_container: AppContainer, governance_data: dict
) -> None:
    message_id = UUID(str(governance_data["message_id"]))
    prefix = governance_data["policy_prefix"]
    full_container.policy_service.create_policy(
        policy_key=f"{prefix}mute",
        name="集成测试禁言策略",
        description="synthetic mute policy",
        policy_type=PolicyType.KEYWORD.value,
        target_scope={"players": [governance_data["sender_ref"]]},
        conditions={"field": "content", "op": "contains", "value": "免费"},
        action=DecisionAction.MUTE.value,
        priority=1000,
        emergency=True,
        created_by="it.reviewer",
        change_reason="force mute action",
    )
    evaluation = full_container.policy_evaluation_service.evaluate_message(message_id)
    decision = full_container.governance_decision_service.make_decision(evaluation)
    decision_id = UUID(str(decision["id"]))
    player_ref = governance_data["sender_ref"]
    service = full_container.enforcement_service
    assert decision["action"] == DecisionAction.MUTE.value

    muted = service.simulate_enforcement(
        decision_id=decision_id,
        action=DecisionAction.MUTE.value,
        target_ref=player_ref,
        reason="integration test mute",
        actor_ref="governance-engine",
        duration_seconds=60,
    )
    enforcement_id = UUID(str(muted["id"]))
    assert muted["simulated"] is True
    assert muted["status"] == "executed"

    state = service.get_player_enforcement_state(player_ref, scope_ref="s1", fresh=True)
    assert state is not None
    assert service.is_player_restricted(player_ref, scope_ref="s1")["muted"] is True

    repeated = service.simulate_enforcement(
        decision_id=decision_id,
        action=DecisionAction.MUTE.value,
        target_ref=player_ref,
        reason="integration test mute replay",
        actor_ref="governance-engine",
        duration_seconds=60,
    )
    assert UUID(str(repeated["id"])) == enforcement_id
    with full_container.session_factory() as session:
        assert _count(session, EnforcementAction, decision_id=decision_id) == 1

    released = service.release_enforcement(
        enforcement_id, actor_ref="it.admin", reason="manual release"
    )
    assert released["status"] == "released"
    assert service.is_player_restricted(player_ref, scope_ref="s1")["muted"] is False

    failed = service.simulate_enforcement(
        decision_id=decision_id,
        action=DecisionAction.MUTE.value,
        target_ref=f"{player_ref}-failure-probe",
        reason="forced failure test",
        actor_ref="governance-engine",
        force_failure=True,
    )
    assert failed["status"] == "failed"


@pytest.mark.integration
def test_feedback_and_audit_are_append_only_on_postgresql(
    full_container: AppContainer, governance_data: dict
) -> None:
    message_id = UUID(str(governance_data["message_id"]))
    evaluation = full_container.policy_evaluation_service.evaluate_message(message_id)
    decision = full_container.governance_decision_service.make_decision(evaluation)
    feedback_service = full_container.feedback_audit_service

    submitted = feedback_service.submit_feedback(
        message_id=message_id,
        feedback_type=FeedbackType.LEVEL_ERROR.value,
        difference_reason="human corrected risk level",
        reviewer_ref="it.reviewer",
        decision_id=UUID(str(decision["id"])),
        final_risk={"risk_level": RiskSeverity.LOW.value},
    )
    assert submitted["is_error_case"] is True
    feedback_id = UUID(str(submitted["id"]))

    feedback = feedback_service.get_feedback(limit=10)
    assert any(item["id"] == str(feedback_id) for item in feedback)
    assert feedback_service.feedback_stats()["total"] >= 1

    error_cases = feedback_service.get_error_cases(limit=10)
    assert any(item["id"] == str(feedback_id) for item in error_cases)

    decision_service = full_container.governance_decision_service
    overridden = decision_service.override_decision(
        UUID(str(decision["id"])),
        actor_ref="it.admin",
        reason="human override after second review",
        status=GovernanceDecisionStatus.OVERRIDDEN.value,
    )
    assert overridden["decision_status"] == GovernanceDecisionStatus.OVERRIDDEN.value

    audit = feedback_service.get_audit_logs(limit=50)
    assert any(item["action"] == "decision.overridden" for item in audit)
    trace = feedback_service.trace(message_id)
    assert trace["message"]["id"] == str(message_id)
    assert trace["evaluations"]

    with full_container.session_factory() as session:
        assert _count(session, GovernanceFeedback, message_id=message_id) == 1
        assert _count(session, AuditEvent, entity_id=UUID(str(decision["id"]))) >= 2
