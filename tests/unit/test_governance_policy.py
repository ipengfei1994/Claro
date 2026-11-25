"""Unit tests for the deterministic policy evaluation domain logic."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from claro.domain.enums import DecisionAction, PolicyType, RiskSeverity
from claro.governance.policy import (
    PolicyContext,
    PolicySnapshot,
    PolicyValidationError,
    evaluate_conditions,
    evaluate_policies,
    find_policy_conflicts,
    policies_snapshot_hash,
    policy_snapshot_hash,
    validate_policy_definition,
)

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def make_context(
    *,
    content: str = "hello alliance",
    risk_score: float = 0.1,
    risk_level: str = RiskSeverity.NORMAL.value,
    confidence: float = 0.95,
    categories: tuple[str, ...] = (),
    sender_ref: str = "player.001",
    server_ref: str | None = "server.01",
    alliance_id: str | None = "alliance.01",
    rate_count: int = 0,
) -> PolicyContext:
    return PolicyContext(
        message_id=UUID("00000000-0000-0000-0000-000000000001"),
        content=content,
        content_hash="hash-1",
        channel="alliance",
        language="zh",
        sender_ref=sender_ref,
        server_ref=server_ref,
        alliance_id=alliance_id,
        risk_score=risk_score,
        risk_level=risk_level,
        confidence=confidence,
        categories=categories,
        category_scores={"fraud": risk_score},
        rate_count=rate_count,
        occurred_at=NOW,
    )


def make_policy(
    key: str,
    *,
    policy_type: str = PolicyType.KEYWORD.value,
    conditions: dict | None = None,
    action: str = DecisionAction.BLOCK.value,
    priority: int = 50,
    emergency: bool = False,
    enabled: bool = True,
    target_scope: dict | None = None,
    version: int = 1,
    effective_from: datetime | None = None,
    effective_until: datetime | None = None,
) -> PolicySnapshot:
    return PolicySnapshot(
        policy_id=UUID(hashlib.sha256(key.encode()).hexdigest()[:32]),
        policy_key=key,
        name=key,
        description="unit test policy",
        policy_type=policy_type,
        target_scope=target_scope or {},
        conditions=conditions or {"field": "content", "op": "contains", "value": "spam"},
        action=action,
        priority=priority,
        emergency=emergency,
        enabled=enabled,
        version=version,
        effective_from=effective_from or NOW - timedelta(days=1),
        effective_until=effective_until,
        created_by="unit-test",
    )


class TestPolicyValidation:
    def test_valid_keyword_definition(self) -> None:
        result = validate_policy_definition(
            policy_type=PolicyType.KEYWORD.value,
            conditions={"field": "text", "op": "contains", "value": "广告"},
            target_scope={"players": ["player.001"]},
            action=DecisionAction.WARN.value,
            priority=10,
        )
        assert result["conditions"]["field"] == "text"  # alias normalized at evaluation time
        assert result["target_scope"]["players"] == ["player.001"]

    def test_rejects_unknown_policy_type(self) -> None:
        with pytest.raises(PolicyValidationError, match="unknown policy type"):
            validate_policy_definition(
                policy_type="arbitrary",
                conditions={"field": "content", "op": "contains", "value": "x"},
                target_scope={},
                action=DecisionAction.WARN.value,
                priority=1,
            )

    def test_rejects_unknown_scope_key(self) -> None:
        with pytest.raises(PolicyValidationError, match="unknown keys"):
            validate_policy_definition(
                policy_type=PolicyType.KEYWORD.value,
                conditions={"field": "content", "op": "contains", "value": "x"},
                target_scope={"countries": ["CN"]},
                action=DecisionAction.WARN.value,
                priority=1,
            )

    def test_rejects_deeply_nested_conditions(self) -> None:
        node: dict = {"field": "content", "op": "contains", "value": "x"}
        for _ in range(7):
            node = {"all": [node]}
        with pytest.raises(PolicyValidationError, match="nesting depth"):
            validate_policy_definition(
                policy_type=PolicyType.KEYWORD.value,
                conditions=node,
                target_scope={},
                action=DecisionAction.WARN.value,
                priority=1,
            )

    @pytest.mark.parametrize("pattern", ["(?=abc)foo", "(?i)abc", "foo\\1"])
    def test_rejects_unsafe_regex(self, pattern: str) -> None:
        with pytest.raises(PolicyValidationError):
            validate_policy_definition(
                policy_type=PolicyType.REGEX.value,
                conditions={"field": "content", "op": "regex", "value": pattern},
                target_scope={},
                action=DecisionAction.BLOCK.value,
                priority=1,
            )

    def test_keyword_requires_content_condition(self) -> None:
        with pytest.raises(PolicyValidationError, match="requires a condition on field 'content'"):
            validate_policy_definition(
                policy_type=PolicyType.KEYWORD.value,
                conditions={"field": "risk_score", "op": "gte", "value": 0.5},
                target_scope={},
                action=DecisionAction.BLOCK.value,
                priority=1,
            )

    def test_numeric_field_rejects_string_value(self) -> None:
        with pytest.raises(PolicyValidationError, match="requires numeric values"):
            validate_policy_definition(
                policy_type=PolicyType.RISK_THRESHOLD.value,
                conditions={"field": "risk_score", "op": "gte", "value": "high"},
                target_scope={},
                action=DecisionAction.BLOCK.value,
                priority=1,
            )


class TestConditionEvaluation:
    def test_all_any_not_composition(self) -> None:
        conditions = {
            "all": [
                {"field": "content", "op": "contains", "value": "广告"},
                {
                    "any": [
                        {"field": "risk_score", "op": "gte", "value": 0.8},
                        {"field": "category", "op": "in", "value": ["spam"]},
                    ]
                },
                {"not": {"field": "sender_ref", "op": "eq", "value": "trusted.bot"}},
            ]
        }
        result = evaluate_conditions(
            conditions, make_context(content="低价广告", risk_score=0.2, categories=("spam",))
        )
        assert result.matched is True
        assert len(result.leaves) == 4

    def test_regex_is_case_insensitive(self) -> None:
        result = evaluate_conditions(
            {"field": "content", "op": "regex", "value": "免费.*领取"},
            make_context(content="免费领取金币"),
        )
        assert result.matched is True

    def test_not_contains(self) -> None:
        result = evaluate_conditions(
            {"field": "content", "op": "not_contains", "value": "诈骗"},
            make_context(content="正常聊天"),
        )
        assert result.matched is True

    def test_exists_on_optional_field(self) -> None:
        assert (
            evaluate_conditions(
                {"field": "alliance_id", "op": "exists"}, make_context(alliance_id=None)
            ).matched
            is False
        )
        assert (
            evaluate_conditions(
                {"field": "alliance_id", "op": "exists"}, make_context(alliance_id="a1")
            ).matched
            is True
        )


class TestPolicyPriorityAndConflicts:
    def test_emergency_beats_priority(self) -> None:
        normal = make_policy("p_priority", priority=999, action=DecisionAction.BLOCK.value)
        emergency = make_policy(
            "p_emergency", priority=1, emergency=True, action=DecisionAction.WARN.value
        )
        conditions = {"field": "content", "op": "contains", "value": "spam"}
        normal = make_policy("p_priority", conditions=conditions, priority=999)
        emergency = make_policy(
            "p_emergency",
            conditions=conditions,
            priority=1,
            emergency=True,
            action=DecisionAction.WARN.value,
        )
        outcome = evaluate_policies(
            make_context(content="spam message"),
            [normal, emergency],
            default_policy=None,
            now=NOW,
        )
        assert outcome.selected_policy is not None
        assert outcome.selected_policy.policy_key == "p_emergency"
        assert outcome.action == DecisionAction.WARN.value

    def test_higher_priority_wins(self) -> None:
        conditions = {"field": "content", "op": "contains", "value": "spam"}
        low = make_policy(
            "p_low", conditions=conditions, priority=10, action=DecisionAction.WARN.value
        )
        high = make_policy(
            "p_high", conditions=conditions, priority=90, action=DecisionAction.BLOCK.value
        )
        outcome = evaluate_policies(
            make_context(content="spam"), [low, high], default_policy=None, now=NOW
        )
        assert outcome.selected_policy is not None
        assert outcome.selected_policy.policy_key == "p_high"

    def test_scope_specificity_breaks_priority_tie(self) -> None:
        conditions = {"field": "content", "op": "contains", "value": "spam"}
        player_rule = make_policy(
            "p_player",
            conditions=conditions,
            priority=50,
            target_scope={"players": ["player.001"]},
            action=DecisionAction.WARN.value,
        )
        global_rule = make_policy(
            "p_global", conditions=conditions, priority=50, action=DecisionAction.BLOCK.value
        )
        outcome = evaluate_policies(
            make_context(content="spam"),
            [global_rule, player_rule],
            default_policy=None,
            now=NOW,
        )
        assert outcome.selected_policy is not None
        assert outcome.selected_policy.policy_key == "p_player"
        assert any(conflict["kind"] == "priority_tie" for conflict in outcome.conflicts)

    def test_deterministic_tiebreak_by_policy_key(self) -> None:
        conditions = {"field": "content", "op": "contains", "value": "spam"}
        a = make_policy("p_zzz", conditions=conditions, priority=50)
        b = make_policy("p_aaa", conditions=conditions, priority=50)
        first = evaluate_policies(
            make_context(content="spam"), [a, b], default_policy=None, now=NOW
        )
        second = evaluate_policies(
            make_context(content="spam"), [b, a], default_policy=None, now=NOW
        )
        assert first.action == second.action
        assert first.selected_policy is not None and second.selected_policy is not None
        assert first.selected_policy.policy_key == second.selected_policy.policy_key == "p_aaa"

    def test_more_restrictive_action_wins_tie(self) -> None:
        conditions = {"field": "content", "op": "contains", "value": "spam"}
        warn = make_policy(
            "p_warn", conditions=conditions, priority=50, action=DecisionAction.WARN.value
        )
        ban = make_policy(
            "p_ban", conditions=conditions, priority=50, action=DecisionAction.TEMP_BAN.value
        )
        outcome = evaluate_policies(
            make_context(content="spam"), [warn, ban], default_policy=None, now=NOW
        )
        assert outcome.action == DecisionAction.TEMP_BAN.value

    def test_scope_mismatch_is_unmatched(self) -> None:
        policy = make_policy(
            "p_server",
            target_scope={"servers": ["server.99"]},
        )
        outcome = evaluate_policies(make_context(), [policy], default_policy=None, now=NOW)
        assert not outcome.matched
        assert len(outcome.unmatched) == 1

    def test_expired_policy_is_unmatched(self) -> None:
        policy = make_policy("p_expired", effective_until=NOW - timedelta(seconds=1))
        outcome = evaluate_policies(
            make_context(content="spam"), [policy], default_policy=None, now=NOW
        )
        assert not outcome.matched

    def test_whitelist_does_not_exempt_high_risk(self) -> None:
        whitelist = make_policy(
            "p_whitelist",
            policy_type=PolicyType.WHITELIST.value,
            conditions={"field": "sender_ref", "op": "eq", "value": "player.001"},
            action=DecisionAction.ALLOW.value,
            priority=999,
        )
        outcome = evaluate_policies(
            make_context(risk_level=RiskSeverity.CRITICAL.value),
            [whitelist],
            default_policy=None,
            now=NOW,
        )
        assert outcome.selected_policy is None
        assert outcome.action == DecisionAction.REVIEW.value
        assert "whitelist exemption not applied" in outcome.reason

    def test_whitelist_exempts_medium_risk(self) -> None:
        whitelist = make_policy(
            "p_whitelist",
            policy_type=PolicyType.WHITELIST.value,
            conditions={"field": "sender_ref", "op": "eq", "value": "player.001"},
            action=DecisionAction.ALLOW.value,
            priority=999,
        )
        outcome = evaluate_policies(
            make_context(risk_level=RiskSeverity.MEDIUM.value),
            [whitelist],
            default_policy=None,
            now=NOW,
        )
        assert outcome.action == DecisionAction.ALLOW.value

    def test_default_action_by_risk_level(self) -> None:
        outcome = evaluate_policies(
            make_context(risk_level=RiskSeverity.MEDIUM.value),
            [],
            default_policy=None,
            now=NOW,
        )
        assert outcome.selected_is_default is True
        assert outcome.action == DecisionAction.WARN.value

    def test_find_policy_conflicts_skips_different_priority(self) -> None:
        a = make_policy("p_a", priority=10, action=DecisionAction.WARN.value)
        b = make_policy("p_b", priority=20, action=DecisionAction.BLOCK.value)
        assert find_policy_conflicts([a, b]) == []


class TestSnapshotHashing:
    def test_hash_is_deterministic(self) -> None:
        policy = make_policy("p_hash")
        assert policy_snapshot_hash(policy) == policy_snapshot_hash(policy)

    def test_hash_changes_with_version(self) -> None:
        first = policy_snapshot_hash(make_policy("p_hash", version=1))
        second = policy_snapshot_hash(make_policy("p_hash", version=2))
        assert first != second

    def test_policy_set_hash_is_order_independent(self) -> None:
        a = make_policy("p_a")
        b = make_policy("p_b")
        assert policies_snapshot_hash([a, b]) == policies_snapshot_hash([b, a])
