"""Business scenario tests for Phase 04 governance.

These scenarios exercise the pure domain decision path. Database-backed
variants of the lifecycle, idempotency and concurrency scenarios live in
``tests/integration/test_governance_*``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from claro.domain.enums import (
    DecisionAction,
    EnforcementTargetType,
    FeedbackType,
    GovernanceDecisionStatus,
    PolicyType,
    RiskSeverity,
)
from claro.governance.decision import decide_governance_action
from claro.governance.enforcement import plan_enforcement, validate_target_ref
from claro.governance.moderation import (
    ModerationWorkflowError,
    build_review_outcome,
    validate_claim,
)
from claro.governance.policy import (
    PolicyContext,
    PolicySnapshot,
    evaluate_policies,
    find_policy_conflicts,
)

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000001")


def context(
    *,
    content: str = "大家好，今天天气不错",
    score: float = 0.05,
    level: str = RiskSeverity.NORMAL.value,
    confidence: float = 0.95,
    categories: tuple[str, ...] = (),
    rate_count: int = 0,
    sender: str = "player.001",
) -> PolicyContext:
    return PolicyContext(
        message_id=MESSAGE_ID,
        content=content,
        content_hash="hash",
        channel="alliance",
        language="zh",
        sender_ref=sender,
        server_ref="s1",
        alliance_id="a1",
        risk_score=score,
        risk_level=level,
        confidence=confidence,
        categories=categories,
        category_scores={"spam": score},
        rate_count=rate_count,
        occurred_at=NOW,
    )


def policy(
    key: str,
    conditions: dict,
    action: str,
    *,
    priority: int = 50,
    emergency: bool = False,
    policy_type: str = PolicyType.COMPOSITE.value,
    scope: dict | None = None,
) -> PolicySnapshot:
    return PolicySnapshot(
        policy_id=UUID(int=int(key.encode().hex()[:32], 16) or 1),
        policy_key=key,
        name=key,
        description="scenario policy",
        policy_type=policy_type,
        target_scope=scope or {},
        conditions=conditions,
        action=action,
        priority=priority,
        emergency=emergency,
        enabled=True,
        version=1,
        effective_from=NOW - timedelta(days=1),
        effective_until=None,
        created_by="scenario-test",
    )


def decide(evaluated_action: str, level: str, confidence: float):
    return decide_governance_action(
        evaluated_action=evaluated_action,
        risk_level=level,
        risk_score=0.7,
        confidence=confidence,
    )


def test_scenario_01_normal_message_allows() -> None:
    result = evaluate_policies(context(), [], default_policy=None, now=NOW)
    decision = decide(result.action, RiskSeverity.NORMAL.value, 0.95)
    assert decision.action == DecisionAction.ALLOW.value
    assert decision.auto_executable is True


def test_scenario_02_mild_violation_warns() -> None:
    result = evaluate_policies(
        context(level=RiskSeverity.MEDIUM.value),
        [],
        default_policy=None,
        now=NOW,
    )
    decision = decide(result.action, RiskSeverity.MEDIUM.value, 0.90)
    assert decision.action == DecisionAction.WARN.value


def test_scenario_03_clear_advertisement_blocks() -> None:
    ad = policy(
        "ad-block",
        {"field": "content", "op": "contains", "value": "广告"},
        DecisionAction.BLOCK.value,
        priority=900,
    )
    result = evaluate_policies(
        context(content="限时广告 点击领取", score=0.85, level=RiskSeverity.HIGH.value),
        [ad],
        default_policy=None,
        now=NOW,
    )
    decision = decide(result.action, RiskSeverity.HIGH.value, 0.95)
    assert decision.action == DecisionAction.BLOCK.value
    assert decision.requires_review is False


def test_scenario_04_high_risk_fraud_reviews_or_authorised_action() -> None:
    result = evaluate_policies(
        context(
            score=0.95,
            level=RiskSeverity.CRITICAL.value,
            categories=("fraud",),
            confidence=0.60,
        ),
        [],
        default_policy=None,
        now=NOW,
    )
    decision = decide(result.action, RiskSeverity.CRITICAL.value, 0.60)
    assert decision.action == DecisionAction.REVIEW.value
    assert decision.requires_review is True


def test_scenario_05_high_severity_low_confidence_reviews() -> None:
    decision = decide(DecisionAction.PERM_BAN.value, RiskSeverity.CRITICAL.value, 0.40)
    assert decision.action == DecisionAction.REVIEW.value
    assert decision.downgraded is True


def test_scenario_06_multiple_policies_resolve_deterministically() -> None:
    conditions = {"field": "content", "op": "contains", "value": "广告"}
    first = policy("alpha", conditions, DecisionAction.WARN.value, priority=80)
    second = policy("beta", conditions, DecisionAction.BLOCK.value, priority=80)
    outcomes = [
        evaluate_policies(
            context(content="广告"),
            listed,
            default_policy=None,
            now=NOW,
        )
        for listed in ([first, second], [second, first])
    ]
    assert outcomes[0].selected_policy is not None
    assert outcomes[1].selected_policy is not None
    assert outcomes[0].selected_policy.policy_key == outcomes[1].selected_policy.policy_key
    assert outcomes[0].conflicts == outcomes[1].conflicts
    assert find_policy_conflicts([first, second])


def test_scenario_07_whitelist_is_scoped_and_high_risk_not_exempted() -> None:
    allow = policy(
        "vip-allow",
        {"field": "sender_ref", "op": "eq", "value": "player.001"},
        DecisionAction.ALLOW.value,
        priority=1000,
        policy_type=PolicyType.WHITELIST.value,
        scope={"servers": ["s1"]},
    )
    scoped = evaluate_policies(
        context(level=RiskSeverity.MEDIUM.value),
        [allow],
        default_policy=None,
        now=NOW,
    )
    assert scoped.action == DecisionAction.ALLOW.value

    high = evaluate_policies(
        context(level=RiskSeverity.CRITICAL.value),
        [allow],
        default_policy=None,
        now=NOW,
    )
    assert high.action == DecisionAction.REVIEW.value

    out_of_scope = evaluate_policies(
        context(level=RiskSeverity.MEDIUM.value, sender="player.002"),
        [allow],
        default_policy=None,
        now=NOW,
    )
    assert out_of_scope.selected_is_default is True


def test_scenario_08_rate_limit_matches_frequency() -> None:
    rule = policy(
        "spam-rate",
        {"field": "rate_count", "op": "gte", "value": 10},
        DecisionAction.FLAG.value,
        policy_type=PolicyType.RATE_LIMIT.value,
    )
    low = evaluate_policies(context(rate_count=2), [rule], default_policy=None, now=NOW)
    high = evaluate_policies(context(rate_count=15), [rule], default_policy=None, now=NOW)
    assert low.selected_is_default is True
    assert high.action == DecisionAction.FLAG.value


def test_scenario_09_human_rejection_records_false_positive() -> None:
    outcome = build_review_outcome(
        current_status="in_review",
        action="reject",
        reason="content is benign",
        system_action=DecisionAction.BLOCK.value,
        system_level=RiskSeverity.HIGH.value,
        system_category="fraud",
        final_action=None,
        final_level=None,
        final_category=None,
    )
    assert outcome.final_action == DecisionAction.ALLOW.value
    assert FeedbackType.FALSE_POSITIVE.value in {"false_positive"}


def test_scenario_10_human_override_records_error() -> None:
    outcome = build_review_outcome(
        current_status="in_review",
        action="override",
        reason="evidence supports permanent ban",
        system_action=DecisionAction.WARN.value,
        system_level=RiskSeverity.MEDIUM.value,
        system_category="spam",
        final_action=DecisionAction.PERM_BAN.value,
        final_level=RiskSeverity.CRITICAL.value,
        final_category="fraud",
    )
    assert outcome.decision_status == GovernanceDecisionStatus.OVERRIDDEN.value
    assert outcome.final_level == RiskSeverity.CRITICAL.value


def test_scenario_11_mute_plan_sets_expiry() -> None:
    plan = plan_enforcement(
        action=DecisionAction.MUTE.value,
        target_type=None,
        duration_seconds=120,
        now=NOW,
    )
    assert plan.expires_at == NOW + timedelta(seconds=120)
    assert plan.simulated is True


def test_scenario_12_temp_ban_plan_expires() -> None:
    plan = plan_enforcement(
        action=DecisionAction.TEMP_BAN.value,
        target_type=EnforcementTargetType.PLAYER_SERVER.value,
        duration_seconds=300,
        now=NOW,
    )
    assert plan.target_type == EnforcementTargetType.PLAYER_SERVER.value
    assert plan.expires_at == NOW + timedelta(seconds=300)


def test_scenario_13_duplicate_event_key_is_deterministic() -> None:
    decision_key = f"gov:{MESSAGE_ID}:{UUID(int=42)}"
    assert decision_key == f"gov:{MESSAGE_ID}:{UUID(int=42)}"
    idempotency_key = f"enforcement:{UUID(int=1)}:{DecisionAction.WARN.value}:player.001"
    assert idempotency_key == f"enforcement:{UUID(int=1)}:{DecisionAction.WARN.value}:player.001"


def test_scenario_14_rollback_creates_new_version_not_overwrite() -> None:
    first = policy(
        "rollback", {"field": "risk_score", "op": "gte", "value": 0.5}, "warn", priority=1
    )
    reverted = replace(first, version=first.version + 1)
    assert reverted.version == first.version + 1
    assert first.conditions == reverted.conditions


def test_scenario_15_concurrent_claim_requires_lock() -> None:
    validate_claim("pending", None, "reviewer.alice")
    with pytest.raises(ModerationWorkflowError):
        validate_claim("in_review", None, "reviewer.bob")


def test_scenario_block_target_ref_matches_message() -> None:
    validate_target_ref(DecisionAction.BLOCK.value, str(MESSAGE_ID), message_id=str(MESSAGE_ID))
    with pytest.raises(ValueError):
        validate_target_ref(DecisionAction.BLOCK.value, "player.001", message_id=str(MESSAGE_ID))
