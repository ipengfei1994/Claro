"""Integration tests: governance cache behaviour against real Redis."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from claro.bootstrap import AppContainer
from claro.domain.enums import DecisionAction


@pytest.mark.integration
def test_policy_cache_serves_snapshots_and_invalidates(
    full_container: AppContainer, governance_data: dict
) -> None:
    service = full_container.policy_service
    cache = full_container.cache
    assert cache is not None
    service.invalidate()
    first = service.active_snapshots(now=datetime.now(UTC))
    assert first

    cached = service._read_cache()
    assert cached is not None
    assert len(cached) == len(first)

    second = service.active_snapshots(now=datetime.now(UTC))
    assert [item.policy_key for item in second] == [item.policy_key for item in first]

    prefix = governance_data["policy_prefix"]
    service.create_policy(
        policy_key=f"{prefix}cache-probe",
        name="缓存失效探测策略",
        description="synthetic cache probe",
        policy_type="keyword",
        target_scope={},
        conditions={"field": "content", "op": "contains", "value": "cache-probe-marker"},
        action=DecisionAction.FLAG.value,
        priority=10,
        created_by="it.reviewer",
        change_reason="verify cache invalidation",
    )
    refreshed = service.active_snapshots(now=datetime.now(UTC))
    assert any(item.policy_key.endswith("cache-probe") for item in refreshed)
    service.invalidate()


@pytest.mark.integration
def test_rate_counter_is_cached_per_time_bucket(
    full_container: AppContainer, governance_data: dict
) -> None:
    cache_service = full_container.governance_cache
    assert cache_service is not None
    sender_ref = governance_data["sender_ref"]
    moment = datetime.now(UTC)
    first = cache_service.sender_message_rate(sender_ref, now=moment)
    second = cache_service.sender_message_rate(sender_ref, now=moment)
    assert first == second >= 0

    raw = full_container.cache.get(
        cache_service._key("rate", f"{sender_ref}:{int(moment.timestamp()) // 20}")
    )
    assert raw is not None


@pytest.mark.integration
def test_player_state_cache_is_invalidated_on_release(
    full_container: AppContainer, governance_data: dict
) -> None:
    message_id = UUID(str(governance_data["message_id"]))
    prefix = governance_data["policy_prefix"]
    full_container.policy_service.create_policy(
        policy_key=f"{prefix}warn-cache",
        name="缓存测试警告策略",
        description="synthetic warn policy",
        policy_type="keyword",
        target_scope={"players": [governance_data["sender_ref"]]},
        conditions={"field": "content", "op": "contains", "value": "免费"},
        action=DecisionAction.WARN.value,
        priority=1000,
        emergency=True,
        created_by="it.reviewer",
        change_reason="force warn action",
    )
    evaluation = full_container.policy_evaluation_service.evaluate_message(message_id)
    decision = full_container.governance_decision_service.make_decision(evaluation)
    assert decision["action"] == DecisionAction.WARN.value

    service = full_container.enforcement_service
    player_ref = governance_data["sender_ref"]
    result = service.simulate_enforcement(
        decision_id=UUID(str(decision["id"])),
        action=DecisionAction.WARN.value,
        target_ref=player_ref,
        reason="cache integration test warn",
        actor_ref="governance-engine",
        scope_ref="s1",
    )
    enforcement_id = UUID(str(result["id"]))

    cached = service.get_player_enforcement_state(player_ref, scope_ref="s1")
    assert cached is not None
    service.release_enforcement(enforcement_id, actor_ref="it.admin", reason="clear cached state")
    after = service.get_player_enforcement_state(player_ref, scope_ref="s1")
    assert after is not None
    assert after["warn_count"] == cached["warn_count"]
