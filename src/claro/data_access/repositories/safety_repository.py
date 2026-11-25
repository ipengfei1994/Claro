from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from claro.data_access.database import session_scope
from claro.data_access.models import (
    AuditEvent,
    DetectionRule,
    Message,
    PlayerBlacklistEntry,
    Policy,
    RiskEvent,
)
from claro.domain.enums import RuleStatus, RuleType
from claro.domain.safety import BlacklistEntry


class SafetyRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def sensitive_words(self, dataset_id: UUID | None, now: datetime) -> tuple[str, ...]:
        conditions = [
            DetectionRule.status == RuleStatus.ACTIVE.value,
            DetectionRule.rule_type == RuleType.KEYWORD.value,
            DetectionRule.effective_from <= now,
            or_(DetectionRule.effective_to.is_(None), DetectionRule.effective_to > now),
        ]
        conditions.append(
            DetectionRule.dataset_id.is_(None)
            if dataset_id is None
            else DetectionRule.dataset_id == dataset_id
        )
        with session_scope(self._sessions) as session:
            rows = session.scalars(select(DetectionRule.definition).where(*conditions)).all()
        words = {
            word.strip()
            for definition in rows
            for word in definition.get("keywords", [])
            if isinstance(word, str) and word.strip()
        }
        return tuple(sorted(words, key=str.casefold))

    def active_policy(
        self, policy_key: str, dataset_id: UUID | None, now: datetime
    ) -> dict[str, Any] | None:
        conditions = [
            Policy.policy_key == policy_key,
            Policy.status == RuleStatus.ACTIVE.value,
            Policy.effective_from <= now,
            or_(Policy.effective_to.is_(None), Policy.effective_to > now),
        ]
        conditions.append(
            Policy.dataset_id.is_(None) if dataset_id is None else Policy.dataset_id == dataset_id
        )
        statement = select(Policy).where(*conditions).order_by(Policy.version.desc()).limit(1)
        with session_scope(self._sessions) as session:
            policy = session.scalar(statement)
            if policy is None:
                return None
            return {
                "id": str(policy.id),
                "policy_key": policy.policy_key,
                "version": policy.version,
                "definition": policy.definition,
                "effective_from": policy.effective_from.isoformat(),
                "is_synthetic": policy.is_synthetic,
            }

    def blacklist_entry(self, player_ref: str) -> BlacklistEntry | None:
        with session_scope(self._sessions) as session:
            entry = session.scalar(
                select(PlayerBlacklistEntry).where(PlayerBlacklistEntry.player_ref == player_ref)
            )
            return _to_blacklist_entry(entry)

    def block_player(
        self,
        player_ref: str,
        reason: str,
        blocked_until: datetime | None,
        is_synthetic: bool,
        actor_ref: str,
        now: datetime,
    ) -> BlacklistEntry:
        with session_scope(self._sessions) as session:
            entry = session.scalar(
                select(PlayerBlacklistEntry).where(PlayerBlacklistEntry.player_ref == player_ref)
            )
            if entry is None:
                entry = PlayerBlacklistEntry(player_ref=player_ref)
                session.add(entry)
            entry.reason = reason
            entry.blocked_until = blocked_until
            entry.is_synthetic = is_synthetic
            entry.updated_at = now
            session.flush()
            session.add(
                AuditEvent(
                    entity_type="player_blacklist_entry",
                    entity_id=entry.id,
                    action="player_blocked",
                    actor_type="operator",
                    actor_ref=actor_ref,
                    details={
                        "player_ref": player_ref,
                        "blocked_until": blocked_until.isoformat() if blocked_until else None,
                        "is_synthetic": is_synthetic,
                    },
                    created_at=now,
                )
            )
            return _to_blacklist_entry(entry)

    def unblock_player(self, player_ref: str, actor_ref: str, now: datetime) -> bool:
        with session_scope(self._sessions) as session:
            entry = session.scalar(
                select(PlayerBlacklistEntry).where(PlayerBlacklistEntry.player_ref == player_ref)
            )
            if entry is None:
                return False
            session.add(
                AuditEvent(
                    entity_type="player_blacklist_entry",
                    entity_id=entry.id,
                    action="player_unblocked",
                    actor_type="operator",
                    actor_ref=actor_ref,
                    details={"player_ref": player_ref, "is_synthetic": entry.is_synthetic},
                    created_at=now,
                )
            )
            session.delete(entry)
            return True

    def player_risk_count(self, player_ref: str, since: datetime) -> int:
        statement = (
            select(func.count())
            .select_from(RiskEvent)
            .join(Message, Message.id == RiskEvent.message_id)
            .where(and_(Message.sender_ref == player_ref, RiskEvent.occurred_at >= since))
        )
        with session_scope(self._sessions) as session:
            return int(session.scalar(statement) or 0)


def _to_blacklist_entry(entry: PlayerBlacklistEntry | None) -> BlacklistEntry | None:
    if entry is None:
        return None
    if entry.blocked_until is not None and entry.blocked_until.tzinfo is None:
        blocked_until = entry.blocked_until.replace(tzinfo=UTC)
    else:
        blocked_until = entry.blocked_until
    return BlacklistEntry(
        id=entry.id,
        player_ref=entry.player_ref,
        reason=entry.reason,
        blocked_until=blocked_until,
        is_synthetic=entry.is_synthetic,
    )
