from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from claro.application.governance_cache import GovernanceCacheService
from claro.data_access.repositories.governance_repository import (
    GovernanceNotFoundError,
    GovernanceRepository,
    GovernanceValidationError,
)
from claro.domain.enums import EnforcementTargetType
from claro.governance.enforcement import ENFORCEMENT_ACTIONS


class EnforcementService:
    """Simulate in-platform enforcement for a governance decision.

    Every record is written with ``simulated = true``. Nothing here touches a
    real game service or mutates real player data; it only records what a real
    enforcement would have done and mirrors it into the simulated player state.
    """

    def __init__(
        self,
        repository: GovernanceRepository,
        *,
        cache: GovernanceCacheService | None = None,
    ) -> None:
        self._repository = repository
        self._cache = cache
        self._logger = structlog.get_logger(__name__)

    def simulate_enforcement(
        self,
        *,
        decision_id: UUID,
        action: str,
        target_ref: str,
        reason: str,
        actor_ref: str,
        target_type: str | None = None,
        duration_seconds: int | None = None,
        scope_ref: str | None = None,
        force_failure: bool = False,
    ) -> dict[str, Any]:
        if action not in ENFORCEMENT_ACTIONS:
            raise GovernanceValidationError(
                f"action '{action}' cannot be enforced; "
                f"expected one of {sorted(ENFORCEMENT_ACTIONS)}"
            )
        idempotency_key = f"enforcement:{decision_id}:{action}:{target_ref}"
        result = self._repository.execute_enforcement(
            decision_id=decision_id,
            action=action,
            target_ref=target_ref,
            target_type=target_type,
            duration_seconds=duration_seconds,
            reason=reason,
            actor_ref=actor_ref,
            idempotency_key=idempotency_key,
            scope_ref=scope_ref,
            simulate=True,
            force_failure=force_failure,
        )
        self._invalidate(result, target_ref=target_ref, scope_ref=scope_ref)
        return result

    def get_enforcement(self, enforcement_id: UUID) -> dict[str, Any]:
        row = self._repository.get_enforcement(enforcement_id)
        if row is None:
            raise GovernanceNotFoundError(f"enforcement not found: {enforcement_id}")
        return row

    def get_enforcement_history(self, *, limit: int = 200) -> list[dict[str, Any]]:
        return self._repository.list_enforcements(limit=limit)

    def get_player_enforcement_state(
        self, player_ref: str, *, scope_ref: str = "*", fresh: bool = False
    ) -> dict[str, Any] | None:
        if self._cache is not None and not fresh:
            return self._cache.player_state(player_ref, scope_ref)
        return self._repository.player_state(player_ref, scope_ref)

    def list_player_states(self, *, limit: int = 200) -> list[dict[str, Any]]:
        return self._repository.player_states(limit=limit)

    def release_enforcement(
        self,
        enforcement_id: UUID,
        *,
        actor_ref: str,
        reason: str,
    ) -> dict[str, Any]:
        result = self._repository.release_enforcement(
            enforcement_id, actor_ref=actor_ref, reason=reason
        )
        self._invalidate(result, target_ref=str(result.get("target_ref", "")), scope_ref=None)
        return result

    def expire_due_enforcements(self, *, limit: int = 500) -> int:
        expired = self._repository.expire_due_enforcements(limit=limit)
        if expired and self._cache is not None:
            self._logger.info("enforcement_expired", count=expired)
        return expired

    def is_player_restricted(
        self, player_ref: str, *, scope_ref: str = "*", now: datetime | None = None
    ) -> dict[str, Any]:
        """Summarise whether a simulated restriction is currently in effect."""
        moment = now or datetime.now(UTC)
        state = self.get_player_enforcement_state(player_ref, scope_ref=scope_ref)
        if state is None:
            return {
                "player_ref": player_ref,
                "scope_ref": scope_ref,
                "restricted": False,
                "muted": False,
                "banned": False,
                "state": None,
            }
        mute_until = _parse(state.get("mute_until"))
        ban_until = _parse(state.get("ban_until"))
        permanent = bool(state.get("permanent_ban"))
        muted = bool(mute_until and mute_until > moment)
        banned = permanent or bool(ban_until and ban_until > moment)
        return {
            "player_ref": player_ref,
            "scope_ref": scope_ref,
            "restricted": muted or banned,
            "muted": muted,
            "banned": banned,
            "permanent_ban": permanent,
            "state": state,
        }

    def _invalidate(
        self, result: dict[str, Any], *, target_ref: str, scope_ref: str | None
    ) -> None:
        if self._cache is None or result.get("target_type") == EnforcementTargetType.MESSAGE.value:
            return
        if not target_ref:
            return
        scopes = {scope_ref or "*"}
        server_ref = result.get("server_ref")
        if server_ref:
            scopes.add(str(server_ref))
        for current_scope in scopes:
            self._cache.invalidate_player_state(target_ref, current_scope)


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
