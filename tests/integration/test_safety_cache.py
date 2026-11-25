from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from claro.bootstrap import AppContainer
from claro.data_access.database import session_scope
from claro.data_access.models import (
    AuditEvent,
    Dataset,
    DetectionRule,
    Message,
    PlayerBlacklistEntry,
    Policy,
    RiskEvent,
)
from claro.domain.enums import (
    MessageStatus,
    RiskCategory,
    RiskSeverity,
    RuleStatus,
    RuleType,
)
from claro.infrastructure.redis import RedisCacheAdapter


@pytest.mark.integration
def test_real_redis_safety_cache_and_postgresql_fallback(
    full_container: AppContainer,
) -> None:
    service = full_container.safety_cache
    cache = cast(RedisCacheAdapter, full_container.cache)
    assert service is not None
    suffix = uuid4().hex
    actor_ref = f"redis-integration-{suffix}"
    player_ref = f"synthetic-redis-player-{suffix}"
    rule_id = uuid4()
    policy_id = uuid4()
    dataset_id = uuid4()
    message_id = uuid4()
    risk_event_id = uuid4()
    now = datetime.now(UTC)
    content = f"Synthetic Redis integration message {suffix}"
    word = f"缓存测试词{suffix}"
    policy_key = f"synthetic-redis-policy-{suffix}"

    with session_scope(full_container.session_factory) as session:
        session.add_all(
            [
                DetectionRule(
                    id=rule_id,
                    rule_key=f"synthetic-redis-rule-{suffix}",
                    version=1,
                    rule_type=RuleType.KEYWORD.value,
                    definition={"keywords": [word], "case_sensitive": False},
                    status=RuleStatus.ACTIVE.value,
                    effective_from=now - timedelta(minutes=1),
                    is_synthetic=True,
                ),
                Policy(
                    id=policy_id,
                    policy_key=policy_key,
                    version=1,
                    status=RuleStatus.ACTIVE.value,
                    definition={"action": "allow", "synthetic": True},
                    effective_from=now - timedelta(minutes=1),
                    is_synthetic=True,
                ),
                Dataset(
                    id=dataset_id,
                    name=f"phase-02-synthetic-redis-{suffix}",
                    seed=20261125,
                    generation_params={"template_version": 2, "synthetic": True},
                    is_synthetic=True,
                ),
            ]
        )
        session.flush()
        session.add(
            Message(
                id=message_id,
                dataset_id=dataset_id,
                external_message_id=f"synthetic-redis-message-{suffix}",
                sender_ref=player_ref,
                channel="world",
                content=content,
                content_hash=sha256(content.encode()).hexdigest(),
                status=MessageStatus.RECEIVED.value,
                occurred_at=now,
                is_synthetic=True,
            )
        )
        session.flush()
        session.add(
            RiskEvent(
                id=risk_event_id,
                dataset_id=dataset_id,
                message_id=message_id,
                rule_id=rule_id,
                category=RiskCategory.FRAUD.value,
                event_type="detected",
                risk_score=0.9,
                confidence=0.95,
                severity=RiskSeverity.HIGH.value,
                occurred_at=now,
                details={"synthetic": True},
                is_synthetic=True,
            )
        )

    ttl_key = f"claro:integration:ttl:{suffix}"
    service.invalidate_sensitive_words()
    try:
        cache.set(ttl_key, "connected", ttl_seconds=30)
        assert 0 < cache.ttl(ttl_key) <= 30

        assert word in service.sensitive_words()
        assert word in service.sensitive_words()
        replacement_word = f"缓存更新词{suffix}"
        with session_scope(full_container.session_factory) as session:
            rule = session.get(DetectionRule, rule_id)
            assert rule is not None
            rule.definition = {"keywords": [replacement_word], "case_sensitive": False}
        assert word in service.sensitive_words()
        service.invalidate_sensitive_words()
        current_words = service.sensitive_words()
        assert replacement_word in current_words
        assert word not in current_words

        policy = service.active_policy(policy_key)
        assert policy is not None and policy["version"] == 1
        with session_scope(full_container.session_factory) as session:
            stored_policy = session.get(Policy, policy_id)
            assert stored_policy is not None
            stored_policy.definition = {"action": "review", "synthetic": True}
        assert service.active_policy(policy_key) == policy
        service.invalidate_policy(policy_key)
        updated_policy = service.active_policy(policy_key)
        assert updated_policy is not None
        assert updated_policy["definition"]["action"] == "review"

        assert not service.is_blacklisted(player_ref)
        entry = service.block_player(
            player_ref,
            "Synthetic Redis integration block",
            blocked_until=now + timedelta(hours=1),
            is_synthetic=True,
            actor_ref=actor_ref,
            now=now,
        )
        assert service.is_blacklisted(player_ref, now)
        assert service.blacklist_entry(player_ref, now) == entry
        with session_scope(full_container.session_factory) as session:
            audit_count = session.scalar(
                select(1)
                .select_from(AuditEvent)
                .where(
                    AuditEvent.action == "player_blocked",
                    AuditEvent.actor_ref == actor_ref,
                )
            )
            assert audit_count == 1
        assert service.unblock_player(player_ref, actor_ref=actor_ref)
        assert not service.is_blacklisted(player_ref, now)

        assert service.player_risk_count(player_ref) == 1
        assert service.player_risk_count(player_ref) == 1

        decisions = [
            service.check_rate_limit(player_ref, limit=2, window_seconds=60) for _ in range(3)
        ]
        assert [decision.allowed for decision in decisions] == [True, True, False]
        assert decisions[-1].retry_after_seconds > 0
    finally:
        cache.delete(ttl_key)
        service.invalidate_sensitive_words()
        service.invalidate_policy(policy_key)
        service.unblock_player(player_ref, actor_ref=actor_ref)
        with session_scope(full_container.session_factory) as session:
            session.execute(
                delete(PlayerBlacklistEntry).where(PlayerBlacklistEntry.player_ref == player_ref)
            )
            session.execute(delete(AuditEvent).where(AuditEvent.actor_ref == actor_ref))
            session.execute(delete(RiskEvent).where(RiskEvent.id == risk_event_id))
            session.execute(delete(Message).where(Message.id == message_id))
            session.execute(delete(Dataset).where(Dataset.id == dataset_id))
            session.execute(delete(DetectionRule).where(DetectionRule.id == rule_id))
            session.execute(delete(Policy).where(Policy.id == policy_id))
