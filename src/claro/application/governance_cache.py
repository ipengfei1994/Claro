from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import structlog
from redis.exceptions import RedisError

from claro.application.ports import CachePort
from claro.data_access.repositories.governance_repository import GovernanceRepository


class GovernanceCacheService:
    """Redis cache for governance read models.

    PostgreSQL remains the authoritative source of business state. Every value
    served here can be recomputed from the database, so a Redis failure only
    degrades latency and never corrupts state. Cache writes never participate in
    a business transaction.
    """

    def __init__(
        self,
        cache: CachePort,
        repository: GovernanceRepository,
        *,
        rate_window_seconds: int = 60,
        rate_ttl_seconds: int = 20,
        player_state_ttl_seconds: int = 30,
    ) -> None:
        if min(rate_window_seconds, rate_ttl_seconds, player_state_ttl_seconds) < 1:
            raise ValueError("governance cache TTLs must be positive")
        self._cache = cache
        self._repository = repository
        self._rate_window = rate_window_seconds
        self._rate_ttl = min(rate_ttl_seconds, rate_window_seconds)
        self._player_state_ttl = player_state_ttl_seconds
        self._logger = structlog.get_logger(__name__)

    def sender_message_rate(self, sender_ref: str, *, now: datetime | None = None) -> int:
        """Return the number of messages a sender produced in the active window.

        The value comes from PostgreSQL and is cached in Redis against a time
        bucket, so repeated evaluation of one message cannot inflate the count.
        """
        moment = now or datetime.now(UTC)
        bucket = int(moment.timestamp()) // self._rate_ttl
        key = self._key("rate", f"{sender_ref}:{bucket}")
        cached = self._read(key)
        if cached is not None:
            count = cached.get("count")
            if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                return count
            self._logger.warning("governance_rate_cache_invalid", cache_key=key)
        count = self._repository.sender_message_rate(
            sender_ref, window_seconds=self._rate_window, now=moment
        )
        self._write(key, {"count": count}, self._rate_ttl)
        return count

    def player_state(self, player_ref: str, scope_ref: str = "*") -> dict[str, Any] | None:
        key = self._key("player-state", f"{player_ref}:{scope_ref}")
        cached = self._read(key)
        if cached is not None and "state" in cached:
            state = cached["state"]
            if state is None or isinstance(state, dict):
                return state
            self._logger.warning("governance_player_state_cache_invalid", cache_key=key)
        state = self._repository.player_state(player_ref, scope_ref)
        self._write(key, {"state": state}, self._player_state_ttl)
        return state

    def invalidate_player_state(self, player_ref: str, scope_ref: str = "*") -> None:
        self._invalidate(self._key("player-state", f"{player_ref}:{scope_ref}"))

    def _read(self, key: str) -> dict[str, Any] | None:
        try:
            raw = self._cache.get(key)
        except RedisError as error:
            self._logger.warning("governance_cache_read_failed", cache_key=key, error=str(error))
            return None
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            self._logger.warning("governance_cache_payload_invalid", cache_key=key)
            return None
        if not isinstance(value, dict):
            self._logger.warning("governance_cache_payload_invalid", cache_key=key)
            return None
        return value

    def _write(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        try:
            self._cache.set(
                key,
                json.dumps(value, ensure_ascii=False, sort_keys=True),
                ttl_seconds=ttl_seconds,
            )
        except RedisError as error:
            self._logger.warning("governance_cache_write_failed", cache_key=key, error=str(error))

    def _invalidate(self, key: str) -> None:
        try:
            self._cache.delete(key)
        except RedisError as error:
            self._logger.warning(
                "governance_cache_invalidation_failed", cache_key=key, error=str(error)
            )

    @staticmethod
    def _key(kind: str, scope: str) -> str:
        digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()
        return f"claro:cache:v1:governance:{kind}:{digest}"
