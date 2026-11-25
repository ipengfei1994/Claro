from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import structlog
from redis.exceptions import RedisError

from claro.application.ports import CachePort
from claro.data_access.repositories.policy_repository import (
    PolicyRepository,
    PolicyRepositoryError,
)
from claro.domain.enums import PolicyType
from claro.governance.policy import (
    PolicyContext,
    PolicySnapshot,
    evaluate_policies,
    validate_policy_definition,
)


class PolicyService:
    def __init__(
        self,
        repository: PolicyRepository,
        *,
        cache: CachePort | None = None,
        cache_ttl_seconds: int = 60,
    ) -> None:
        if cache_ttl_seconds < 1:
            raise ValueError("cache_ttl_seconds must be positive")
        self._repository = repository
        self._cache = cache
        self._cache_ttl = cache_ttl_seconds
        self._logger = structlog.get_logger(__name__)

    def create_policy(
        self,
        *,
        policy_key: str,
        name: str,
        description: str,
        policy_type: str,
        target_scope: dict[str, Any],
        conditions: dict[str, Any],
        action: str,
        priority: int,
        created_by: str,
        change_reason: str,
        emergency: bool = False,
        effective_from: datetime | None = None,
        effective_until: datetime | None = None,
    ) -> dict[str, Any]:
        result = self._repository.create_policy(
            policy_key=policy_key,
            name=name,
            description=description,
            policy_type=policy_type,
            target_scope=target_scope,
            conditions=conditions,
            action=action,
            priority=priority,
            emergency=emergency,
            effective_from=effective_from,
            effective_until=effective_until,
            created_by=created_by,
            change_reason=change_reason,
        )
        self.invalidate()
        return result

    def update_policy(
        self,
        policy_id: UUID,
        *,
        actor_ref: str,
        reason: str,
        expected_version: int | None = None,
        **changes: Any,
    ) -> dict[str, Any]:
        result = self._repository.update_policy(
            policy_id,
            actor_ref=actor_ref,
            reason=reason,
            expected_version=expected_version,
            **changes,
        )
        self.invalidate()
        return result

    def set_enabled(
        self, policy_id: UUID, *, enabled: bool, actor_ref: str, reason: str
    ) -> dict[str, Any]:
        result = self._repository.set_enabled(
            policy_id, enabled=enabled, actor_ref=actor_ref, reason=reason
        )
        self.invalidate()
        return result

    def rollback_policy(
        self,
        policy_id: UUID,
        *,
        target_version: int,
        actor_ref: str,
        reason: str,
    ) -> dict[str, Any]:
        result = self._repository.rollback_policy(
            policy_id, target_version=target_version, actor_ref=actor_ref, reason=reason
        )
        self.invalidate()
        return result

    def list_policies(
        self, *, include_disabled: bool = True, dataset_id: UUID | None = None
    ) -> list[dict[str, Any]]:
        return self._repository.list_policies(
            include_disabled=include_disabled, dataset_id=dataset_id
        )

    def get_policy(self, policy_id: UUID) -> dict[str, Any] | None:
        return self._repository.get_policy(policy_id)

    def versions(self, policy_id: UUID) -> list[dict[str, Any]]:
        return self._repository.versions(policy_id)

    def compare_versions(
        self, policy_id: UUID, left_version: int, right_version: int
    ) -> dict[str, Any]:
        return self._repository.compare_versions(policy_id, left_version, right_version)

    def conflict_scan(self) -> list[dict[str, Any]]:
        return self._repository.conflict_scan()

    def ensure_default_policy(self) -> dict[str, Any]:
        result = self._repository.ensure_default_policy()
        self.invalidate()
        return result

    def get_default_snapshot(self) -> PolicySnapshot | None:
        return self._repository.default_policy()

    def increment_hits(self, policy_ids: list[UUID]) -> None:
        """Record that the given policies were applied to a message."""
        self._repository.increment_hits(policy_ids)

    def active_snapshots(
        self, *, now: datetime | None = None, dataset_id: UUID | None = None
    ) -> list[PolicySnapshot]:
        moment = now or datetime.now(UTC)
        if dataset_id is not None:
            return self._repository.active_snapshots(now=moment, dataset_id=dataset_id)
        cached = self._read_cache()
        if cached is not None:
            snapshots = [snapshot_from_dict(item) for item in cached]
            return [item for item in snapshots if item.is_effective(moment)]
        snapshots = self._repository.active_snapshots(now=moment)
        self._write_cache([snapshot_to_dict(item) for item in snapshots])
        return snapshots

    def invalidate(self) -> None:
        if self._cache is None:
            return
        try:
            self._cache.delete(self._cache_key())
        except RedisError as error:
            self._logger.warning("governance_policy_cache_invalidation_failed", error=str(error))

    def playground(
        self,
        *,
        content: str,
        risk_score: float,
        risk_level: str,
        confidence: float,
        sender_ref: str = "synthetic-playground-player",
        server_ref: str | None = "synthetic-server-1",
        channel: str = "world",
        language: str = "zh-CN",
        rate_count: int = 0,
        candidate: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        default_policy = self._repository.default_policy() or _snapshot_from_dict(
            self._repository.ensure_default_policy()
        )
        policies = self.active_snapshots(now=now)
        if candidate is not None:
            candidate_type = str(candidate.get("policy_type", PolicyType.COMPOSITE.value))
            candidate_action = str(candidate.get("action", "review"))
            candidate_priority = int(candidate.get("priority", 100))
            validated = validate_policy_definition(
                policy_type=candidate_type,
                conditions=candidate.get("conditions"),
                target_scope=candidate.get("target_scope", {}),
                action=candidate_action,
                priority=candidate_priority,
            )
            policies = [
                PolicySnapshot(
                    policy_id=uuid4(),
                    policy_key=str(candidate.get("policy_key", "playground-candidate")),
                    name=str(candidate.get("name", "Playground candidate")),
                    description=str(candidate.get("description", "")),
                    policy_type=candidate_type,
                    target_scope=validated["target_scope"],
                    conditions=validated["conditions"],
                    action=candidate_action,
                    priority=candidate_priority,
                    emergency=bool(candidate.get("emergency", False)),
                    enabled=True,
                    version=1,
                    effective_from=now,
                    effective_until=None,
                    created_by="playground",
                    is_synthetic=True,
                )
            ]
        context = PolicyContext(
            message_id=uuid4(),
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            channel=channel,
            language=language,
            sender_ref=sender_ref,
            server_ref=server_ref,
            alliance_id=None,
            risk_score=risk_score,
            risk_level=risk_level,
            confidence=confidence,
            categories=("fraud",) if risk_score >= 0.5 else (),
            category_scores={"fraud": risk_score} if risk_score else {},
            rate_count=rate_count,
            occurred_at=now,
        )
        outcome = evaluate_policies(context, policies, default_policy=default_policy, now=now)
        return {
            "action": outcome.action,
            "reason": outcome.reason,
            "selected_policy": (
                snapshot_to_dict(outcome.selected_policy) if outcome.selected_policy else None
            ),
            "selected_is_default": outcome.selected_is_default,
            "matched": [_match_dict(item) for item in outcome.matched],
            "conflicts": list(outcome.conflicts),
            "snapshot_hash": outcome.snapshot_hash,
            "input": {
                "content": content,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "confidence": confidence,
                "sender_ref": sender_ref,
                "server_ref": server_ref,
                "rate_count": rate_count,
            },
        }

    def _cache_key(self) -> str:
        return "claro:cache:v1:governance:active-policies"

    def _read_cache(self) -> list[dict[str, Any]] | None:
        if self._cache is None:
            return None
        try:
            raw = self._cache.get(self._cache_key())
        except RedisError as error:
            self._logger.warning("governance_policy_cache_read_failed", error=str(error))
            return None
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            self._logger.warning("governance_policy_cache_invalid")
            return None
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            return None
        return value

    def _write_cache(self, value: list[dict[str, Any]]) -> None:
        if self._cache is None:
            return
        try:
            self._cache.set(
                self._cache_key(),
                json.dumps(value, ensure_ascii=False, sort_keys=True, default=str),
                ttl_seconds=self._cache_ttl,
            )
        except RedisError as error:
            self._logger.warning("governance_policy_cache_write_failed", error=str(error))


def snapshot_to_dict(snapshot: PolicySnapshot) -> dict[str, Any]:
    return {
        "policy_id": str(snapshot.policy_id),
        "policy_key": snapshot.policy_key,
        "name": snapshot.name,
        "description": snapshot.description,
        "policy_type": snapshot.policy_type,
        "target_scope": snapshot.target_scope,
        "conditions": snapshot.conditions,
        "action": snapshot.action,
        "priority": snapshot.priority,
        "emergency": snapshot.emergency,
        "enabled": snapshot.enabled,
        "version": snapshot.version,
        "effective_from": snapshot.effective_from.isoformat(),
        "effective_until": (
            snapshot.effective_until.isoformat() if snapshot.effective_until else None
        ),
        "created_by": snapshot.created_by,
        "is_synthetic": snapshot.is_synthetic,
    }


def snapshot_from_dict(value: dict[str, Any]) -> PolicySnapshot:
    try:
        return PolicySnapshot(
            policy_id=UUID(str(value["policy_id"])),
            policy_key=str(value["policy_key"]),
            name=str(value["name"]),
            description=str(value.get("description", "")),
            policy_type=str(value["policy_type"]),
            target_scope=dict(value.get("target_scope", {})),
            conditions=dict(value.get("conditions", {})),
            action=str(value["action"]),
            priority=int(value["priority"]),
            emergency=bool(value["emergency"]),
            enabled=bool(value["enabled"]),
            version=int(value["version"]),
            effective_from=datetime.fromisoformat(str(value["effective_from"])),
            effective_until=(
                datetime.fromisoformat(str(value["effective_until"]))
                if value.get("effective_until")
                else None
            ),
            created_by=str(value.get("created_by", "unknown")),
            is_synthetic=bool(value.get("is_synthetic", True)),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PolicyRepositoryError("cached policy entry is invalid") from error


def _snapshot_from_dict(value: dict[str, Any]) -> PolicySnapshot:
    return snapshot_from_dict(value)


def _match_dict(match: Any) -> dict[str, Any]:
    return {
        "policy_key": match.policy.policy_key,
        "name": match.policy.name,
        "version": match.policy.version,
        "policy_type": match.policy.policy_type,
        "action": match.policy.action,
        "priority": match.policy.priority,
        "emergency": match.policy.emergency,
        "specificity": match.specificity,
        "conditions": list(match.leaves),
    }
