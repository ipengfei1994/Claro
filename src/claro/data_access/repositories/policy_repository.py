from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from claro.data_access.database import session_scope
from claro.data_access.models import AuditEvent, Policy, PolicyVersion
from claro.domain.enums import DecisionAction, PolicyType, RuleStatus
from claro.governance.policy import (
    PolicySnapshot,
    PolicyValidationError,
    find_policy_conflicts,
    policy_snapshot_hash,
    validate_policy_definition,
)

_POLICY_FIELDS = (
    "name",
    "description",
    "policy_type",
    "target_scope",
    "conditions",
    "action",
    "priority",
    "emergency",
    "enabled",
    "effective_from",
    "effective_until",
    "change_reason",
)


class PolicyRepositoryError(ValueError):
    pass


class PolicyRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

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
        emergency: bool,
        effective_from: datetime | None,
        effective_until: datetime | None,
        created_by: str,
        change_reason: str,
        is_synthetic: bool = True,
    ) -> dict[str, Any]:
        _require_text(policy_key, "policy_key", 120)
        _require_text(name, "name", 200)
        _require_text(created_by, "created_by", 191)
        _require_text(change_reason, "change_reason", 2_000)
        validated = validate_policy_definition(
            policy_type=policy_type,
            conditions=conditions,
            target_scope=target_scope,
            action=action,
            priority=priority,
        )
        now = datetime.now(UTC)
        start = effective_from or now
        if start.tzinfo is None:
            raise PolicyValidationError("effective_from must be timezone-aware")
        if effective_until is not None:
            if effective_until.tzinfo is None:
                raise PolicyValidationError("effective_until must be timezone-aware")
            if effective_until <= start:
                raise PolicyValidationError("effective_until must be after effective_from")
        try:
            with session_scope(self._sessions) as session:
                if session.scalar(select(Policy.id).where(Policy.policy_key == policy_key)):
                    raise PolicyRepositoryError(f"policy key already exists: {policy_key}")
                row = Policy(
                    policy_key=policy_key,
                    version=1,
                    status=RuleStatus.ACTIVE.value,
                    definition={
                        "conditions": validated["conditions"],
                        "target_scope": validated["target_scope"],
                    },
                    effective_from=start,
                    effective_to=effective_until,
                    name=name.strip(),
                    description=description.strip(),
                    policy_type=policy_type,
                    target_scope=validated["target_scope"],
                    conditions=validated["conditions"],
                    action=action,
                    priority=priority,
                    emergency=emergency,
                    enabled=True,
                    created_by=created_by,
                    updated_by=created_by,
                    is_synthetic=is_synthetic,
                )
                session.add(row)
                session.flush()
                snapshot = _snapshot_from_row(row)
                session.add(
                    _version_row(snapshot, change_reason, created_by, start, effective_until)
                )
                _audit(
                    session,
                    entity_type="policy",
                    entity_id=row.id,
                    action="policy.created",
                    actor_ref=created_by,
                    actor_role="policy_admin",
                    reason=change_reason,
                    after=_policy_dict(row),
                )
                session.flush()
                return _policy_dict(row)
        except IntegrityError as error:
            raise PolicyRepositoryError(f"policy key already exists: {policy_key}") from error

    def update_policy(
        self,
        policy_id: UUID,
        *,
        actor_ref: str,
        reason: str,
        expected_version: int | None = None,
        **changes: Any,
    ) -> dict[str, Any]:
        _require_text(actor_ref, "actor_ref", 191)
        _require_text(reason, "reason", 2_000)
        unknown = set(changes) - set(_POLICY_FIELDS)
        if unknown:
            raise PolicyRepositoryError(f"unsupported policy changes: {sorted(unknown)}")
        if not changes:
            raise PolicyRepositoryError("at least one policy field must change")
        with session_scope(self._sessions) as session:
            row = session.get(Policy, policy_id)
            if row is None or row.policy_type is None:
                raise PolicyRepositoryError(f"governance policy not found: {policy_id}")
            if expected_version is not None and row.version != expected_version:
                raise PolicyRepositoryError(
                    f"policy version conflict: expected {expected_version}, found {row.version}"
                )
            before = _policy_dict(row)
            merged = {
                "policy_type": row.policy_type,
                "conditions": dict(row.conditions or {}),
                "target_scope": dict(row.target_scope or {}),
                "action": row.action,
                "priority": row.priority,
                "name": row.name or "",
                "description": row.description or "",
                "emergency": row.emergency,
                "enabled": row.enabled,
                "effective_from": changes.get("effective_from", row.effective_from),
                "effective_until": changes.get("effective_until", row.effective_to),
            }
            merged.update({key: value for key, value in changes.items() if key != "change_reason"})
            validated = validate_policy_definition(
                policy_type=str(merged["policy_type"]),
                conditions=merged["conditions"],
                target_scope=merged["target_scope"],
                action=str(merged["action"]),
                priority=int(merged["priority"]),
            )
            if merged["effective_from"].tzinfo is None:
                raise PolicyValidationError("effective_from must be timezone-aware")
            if merged["effective_until"] is not None:
                if merged["effective_until"].tzinfo is None:
                    raise PolicyValidationError("effective_until must be timezone-aware")
                if merged["effective_until"] <= merged["effective_from"]:
                    raise PolicyValidationError("effective_until must be after effective_from")
            row.version += 1
            row.name = str(merged["name"]).strip()
            row.description = str(merged["description"]).strip()
            row.policy_type = str(merged["policy_type"])
            row.target_scope = validated["target_scope"]
            row.conditions = validated["conditions"]
            row.definition = {
                "conditions": validated["conditions"],
                "target_scope": validated["target_scope"],
            }
            row.action = str(merged["action"])
            row.priority = int(merged["priority"])
            row.emergency = bool(merged["emergency"])
            row.enabled = bool(merged["enabled"])
            row.status = RuleStatus.ACTIVE.value if row.enabled else RuleStatus.DISABLED.value
            row.effective_from = merged["effective_from"]
            row.effective_to = merged["effective_until"]
            row.updated_by = actor_ref
            row.updated_at = datetime.now(UTC)
            session.add(
                _version_row(
                    _snapshot_from_row(row),
                    reason,
                    actor_ref,
                    row.effective_from,
                    row.effective_to,
                )
            )
            _audit(
                session,
                entity_type="policy",
                entity_id=row.id,
                action="policy.updated",
                actor_ref=actor_ref,
                actor_role="policy_admin",
                reason=reason,
                before=before,
                after=_policy_dict(row),
            )
            session.flush()
            return _policy_dict(row)

    def set_enabled(
        self,
        policy_id: UUID,
        *,
        enabled: bool,
        actor_ref: str,
        reason: str,
    ) -> dict[str, Any]:
        return self.update_policy(
            policy_id, enabled=enabled, actor_ref=actor_ref, reason=reason
        )

    def rollback_policy(
        self,
        policy_id: UUID,
        *,
        target_version: int,
        actor_ref: str,
        reason: str,
    ) -> dict[str, Any]:
        if not isinstance(target_version, int) or target_version < 1:
            raise PolicyRepositoryError("target_version must be a positive integer")
        with session_scope(self._sessions) as session:
            snapshot = session.scalar(
                select(PolicyVersion).where(
                    PolicyVersion.policy_id == policy_id,
                    PolicyVersion.version == target_version,
                )
            )
            if snapshot is None:
                raise PolicyRepositoryError(
                    f"policy version {target_version} not found for {policy_id}"
                )
            changes = {
                "name": snapshot.name,
                "description": snapshot.description,
                "policy_type": snapshot.policy_type,
                "target_scope": snapshot.target_scope,
                "conditions": snapshot.conditions,
                "action": snapshot.action,
                "priority": snapshot.priority,
                "emergency": snapshot.emergency,
                "enabled": snapshot.enabled,
                "effective_from": snapshot.effective_from,
                "effective_until": snapshot.effective_until,
            }
        return self.update_policy(
            policy_id,
            actor_ref=actor_ref,
            reason=f"rollback to version {target_version}: {reason}",
            **changes,
        )

    def get_policy(self, policy_id: UUID) -> dict[str, Any] | None:
        with session_scope(self._sessions) as session:
            row = session.get(Policy, policy_id)
            if row is None or row.policy_type is None:
                return None
            result = _policy_dict(row)
            result["history"] = [
                _version_dict(item)
                for item in session.scalars(
                    select(PolicyVersion)
                    .where(PolicyVersion.policy_id == policy_id)
                    .order_by(PolicyVersion.version)
                )
            ]
            result["audit"] = _audit_list(session, "policy", policy_id, 50)
            return result

    def find_by_key(self, policy_key: str) -> dict[str, Any] | None:
        with session_scope(self._sessions) as session:
            row = session.scalar(select(Policy).where(Policy.policy_key == policy_key))
            return _policy_dict(row) if row is not None and row.policy_type else None

    def list_policies(
        self, *, include_disabled: bool = True, dataset_id: UUID | None = None
    ) -> list[dict[str, Any]]:
        statement = select(Policy).where(Policy.policy_type.is_not(None))
        if dataset_id is not None:
            statement = statement.where(
                or_(Policy.dataset_id.is_(None), Policy.dataset_id == dataset_id)
            )
        if not include_disabled:
            statement = statement.where(Policy.enabled.is_(True))
        statement = statement.order_by(
            Policy.enabled.desc(), Policy.priority.desc(), Policy.policy_key
        )
        with session_scope(self._sessions) as session:
            return [_policy_dict(row) for row in session.scalars(statement)]

    def active_snapshots(
        self, *, now: datetime, dataset_id: UUID | None = None
    ) -> list[PolicySnapshot]:
        statement = select(Policy).where(Policy.policy_type.is_not(None), Policy.enabled.is_(True))
        if dataset_id is not None:
            statement = statement.where(
                or_(Policy.dataset_id.is_(None), Policy.dataset_id == dataset_id)
            )
        with session_scope(self._sessions) as session:
            rows = session.scalars(statement).all()
        snapshots = [_snapshot_from_row(row) for row in rows]
        return [item for item in snapshots if item.is_effective(now)]

    def all_snapshots(self) -> list[PolicySnapshot]:
        with session_scope(self._sessions) as session:
            return [
                _snapshot_from_row(row)
                for row in session.scalars(
                    select(Policy).where(Policy.policy_type.is_not(None)).order_by(Policy.policy_key)
                )
            ]

    def versions(self, policy_id: UUID) -> list[dict[str, Any]]:
        with session_scope(self._sessions) as session:
            if session.get(Policy, policy_id) is None:
                raise PolicyRepositoryError(f"policy not found: {policy_id}")
            return [
                _version_dict(item)
                for item in session.scalars(
                    select(PolicyVersion)
                    .where(PolicyVersion.policy_id == policy_id)
                    .order_by(PolicyVersion.version)
                )
            ]

    def compare_versions(
        self, policy_id: UUID, left_version: int, right_version: int
    ) -> dict[str, Any]:
        versions = {item["version"]: item for item in self.versions(policy_id)}
        if left_version not in versions or right_version not in versions:
            raise PolicyRepositoryError("both versions must exist before they can be compared")
        left = versions[left_version]
        right = versions[right_version]
        changed = {
            key: {"left": left.get(key), "right": right.get(key)}
            for key in (
                "name",
                "description",
                "policy_type",
                "target_scope",
                "conditions",
                "action",
                "priority",
                "emergency",
                "enabled",
                "effective_from",
                "effective_until",
            )
            if left.get(key) != right.get(key)
        }
        return {
            "policy_id": str(policy_id),
            "left_version": left_version,
            "right_version": right_version,
            "changed": changed,
            "identical": not changed,
        }

    def conflict_scan(self) -> list[dict[str, Any]]:
        return find_policy_conflicts(self.all_snapshots())

    def increment_hits(self, policy_ids: list[UUID]) -> None:
        if not policy_ids:
            return
        with session_scope(self._sessions) as session:
            for policy_id in set(policy_ids):
                row = session.get(Policy, policy_id)
                if row is not None:
                    row.hit_count += 1

    def default_policy(self) -> PolicySnapshot | None:
        with session_scope(self._sessions) as session:
            row = session.scalar(
                select(Policy).where(
                    Policy.policy_key == "governance-default",
                    Policy.policy_type.is_not(None),
                )
            )
            return _snapshot_from_row(row) if row is not None else None

    def ensure_default_policy(self, *, actor_ref: str = "system") -> dict[str, Any]:
        existing = self.find_by_key("governance-default")
        if existing is not None:
            return existing
        now = datetime.now(UTC)
        return self.create_policy(
            policy_key="governance-default",
            name="Default risk-level policy",
            description=(
                "Synthetic fallback policy. Applies the default risk-level action when no "
                "specific policy matches. It is evaluated without a content condition."
            ),
            policy_type=PolicyType.RISK_THRESHOLD.value,
            target_scope={},
            conditions={"field": "risk_score", "op": "gte", "value": 0},
            action=DecisionAction.REVIEW.value,
            priority=0,
            emergency=False,
            effective_from=now,
            effective_until=None,
            created_by=actor_ref,
            change_reason="initialize default governance policy",
            is_synthetic=True,
        )

    def counts(self) -> dict[str, int]:
        with session_scope(self._sessions) as session:
            total = int(
                session.scalar(
                    select(func.count()).select_from(Policy).where(Policy.policy_type.is_not(None))
                )
                or 0
            )
            enabled = int(
                session.scalar(
                    select(func.count())
                    .select_from(Policy)
                    .where(Policy.policy_type.is_not(None), Policy.enabled.is_(True))
                )
                or 0
            )
        return {"policies": total, "enabled": enabled, "disabled": total - enabled}


def _snapshot_from_row(row: Policy) -> PolicySnapshot:
    if row.policy_type is None or row.action is None or row.priority is None:
        raise PolicyRepositoryError(f"policy {row.id} is not a governance policy")
    return PolicySnapshot(
        policy_id=row.id,
        policy_key=row.policy_key,
        name=row.name or row.policy_key,
        description=row.description or "",
        policy_type=row.policy_type,
        target_scope=dict(row.target_scope or {}),
        conditions=dict(row.conditions or {}),
        action=row.action,
        priority=row.priority,
        emergency=row.emergency,
        enabled=row.enabled,
        version=row.version,
        effective_from=row.effective_from,
        effective_until=row.effective_to,
        created_by=row.created_by or "legacy",
        is_synthetic=row.is_synthetic,
    )


def _version_row(
    snapshot: PolicySnapshot,
    change_reason: str,
    created_by: str,
    effective_from: datetime,
    effective_until: datetime | None,
) -> PolicyVersion:
    return PolicyVersion(
        policy_id=snapshot.policy_id,
        version=snapshot.version,
        name=snapshot.name,
        description=snapshot.description,
        policy_type=snapshot.policy_type,
        target_scope=snapshot.target_scope,
        conditions=snapshot.conditions,
        action=snapshot.action,
        priority=snapshot.priority,
        emergency=snapshot.emergency,
        enabled=snapshot.enabled,
        effective_from=effective_from,
        effective_until=effective_until,
        change_reason=change_reason,
        snapshot_hash=policy_snapshot_hash(snapshot),
        created_by=created_by,
    )


def _policy_dict(row: Policy) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "policy_key": row.policy_key,
        "version": row.version,
        "name": row.name or row.policy_key,
        "description": row.description or "",
        "policy_type": row.policy_type,
        "target_scope": dict(row.target_scope or {}),
        "conditions": dict(row.conditions or {}),
        "action": row.action,
        "priority": row.priority,
        "emergency": row.emergency,
        "enabled": row.enabled,
        "status": row.status,
        "effective_from": row.effective_from.isoformat(),
        "effective_until": row.effective_to.isoformat() if row.effective_to else None,
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat(),
        "hit_count": row.hit_count,
        "is_synthetic": row.is_synthetic,
    }


def _version_dict(row: PolicyVersion) -> dict[str, Any]:
    return {
        "version": row.version,
        "name": row.name,
        "description": row.description,
        "policy_type": row.policy_type,
        "target_scope": dict(row.target_scope or {}),
        "conditions": dict(row.conditions or {}),
        "action": row.action,
        "priority": row.priority,
        "emergency": row.emergency,
        "enabled": row.enabled,
        "effective_from": row.effective_from.isoformat(),
        "effective_until": row.effective_until.isoformat() if row.effective_until else None,
        "change_reason": row.change_reason,
        "snapshot_hash": row.snapshot_hash,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
    }


def _audit(
    session: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    action: str,
    actor_ref: str,
    actor_role: str,
    reason: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_type="user",
            actor_ref=actor_ref,
            actor_role=actor_role,
            reason=reason,
            before_state=before,
            after_state=after,
            details={"synthetic": True},
        )
    )


def _audit_list(
    session: Session, entity_type: str, entity_id: UUID, limit: int
) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.entity_type == entity_type, AuditEvent.entity_id == entity_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "action": row.action,
            "actor_ref": row.actor_ref,
            "actor_role": row.actor_role,
            "reason": row.reason,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def _require_text(value: str, name: str, max_length: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise PolicyValidationError(
            f"{name} must be a non-empty string of at most {max_length} characters"
        )
