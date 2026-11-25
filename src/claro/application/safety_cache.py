from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from redis.exceptions import RedisError

from claro.application.ports import BusinessCachePort, CachePort, SafetyRepositoryPort
from claro.domain.safety import BlacklistEntry, RateLimitDecision


class SafetyCacheService:
    def __init__(
        self,
        cache: CachePort,
        repository: SafetyRepositoryPort,
        *,
        configuration_ttl_seconds: int = 300,
        blacklist_ttl_seconds: int = 60,
        negative_ttl_seconds: int = 30,
    ) -> None:
        if min(configuration_ttl_seconds, blacklist_ttl_seconds, negative_ttl_seconds) < 1:
            raise ValueError("cache TTLs must be positive")
        self._cache = cache
        self._repository = repository
        self._configuration_ttl = configuration_ttl_seconds
        self._blacklist_ttl = blacklist_ttl_seconds
        self._negative_ttl = negative_ttl_seconds
        self._logger = structlog.get_logger(__name__)

    def sensitive_words(self, dataset_id: UUID | None = None) -> tuple[str, ...]:
        key = self._configuration_key("sensitive-words", str(dataset_id or "global"))
        cached = self._read(key)
        if cached is not None:
            words = cached.get("words")
            if isinstance(words, list) and all(isinstance(word, str) for word in words):
                return tuple(words)
            self._logger.warning("invalid_sensitive_word_cache", cache_key=key)
        words = self._repository.sensitive_words(dataset_id, datetime.now(UTC))
        self._write(key, {"words": list(words)}, self._configuration_ttl)
        return words

    def invalidate_sensitive_words(self, dataset_id: UUID | None = None) -> None:
        self._invalidate(self._configuration_key("sensitive-words", str(dataset_id or "global")))

    def active_policy(
        self, policy_key: str, dataset_id: UUID | None = None
    ) -> dict[str, Any] | None:
        self._require_text(policy_key, "policy_key", 120)
        key = self._configuration_key("policy", f"{dataset_id or 'global'}:{policy_key}")
        cached = self._read(key)
        if cached is not None and "value" in cached:
            value = cached["value"]
            if value is None or isinstance(value, dict):
                return value
            self._logger.warning("invalid_policy_cache", cache_key=key)
        value = self._repository.active_policy(policy_key, dataset_id, datetime.now(UTC))
        self._write(
            key,
            {"value": value},
            self._configuration_ttl if value is not None else self._negative_ttl,
        )
        return value

    def invalidate_policy(self, policy_key: str, dataset_id: UUID | None = None) -> None:
        self._require_text(policy_key, "policy_key", 120)
        self._invalidate(
            self._configuration_key("policy", f"{dataset_id or 'global'}:{policy_key}")
        )

    def blacklist_entry(
        self, player_ref: str, now: datetime | None = None
    ) -> BlacklistEntry | None:
        self._require_text(player_ref, "player_ref", 191)
        key = self._player_key("blacklist", player_ref)
        cached = self._read(key)
        if cached is not None and "entry" in cached:
            value = cached["entry"]
            if value is None:
                return None
            if isinstance(value, dict):
                try:
                    entry = BlacklistEntry(
                        id=UUID(value["id"]),
                        player_ref=value["player_ref"],
                        reason=value["reason"],
                        blocked_until=(
                            datetime.fromisoformat(value["blocked_until"])
                            if value["blocked_until"]
                            else None
                        ),
                        is_synthetic=value["is_synthetic"],
                    )
                except (KeyError, TypeError, ValueError):
                    self._logger.warning("invalid_blacklist_cache", cache_key=key)
                else:
                    if entry.player_ref != player_ref:
                        self._logger.warning("blacklist_cache_identity_mismatch", cache_key=key)
                    elif entry.is_active(now):
                        return entry
                    else:
                        self._invalidate(key)
        entry = self._repository.blacklist_entry(player_ref)
        if entry is not None and not entry.is_active(now):
            self._write(key, {"entry": None}, self._negative_ttl)
            return None
        self._write(
            key,
            {"entry": _serialize_blacklist_entry(entry)},
            self._blacklist_ttl if entry is not None else self._negative_ttl,
        )
        return entry

    def is_blacklisted(self, player_ref: str, now: datetime | None = None) -> bool:
        return self.blacklist_entry(player_ref, now) is not None

    def block_player(
        self,
        player_ref: str,
        reason: str,
        *,
        blocked_until: datetime | None = None,
        is_synthetic: bool = False,
        actor_ref: str,
        now: datetime | None = None,
    ) -> BlacklistEntry:
        self._require_text(player_ref, "player_ref", 191)
        self._require_text(reason, "reason", 2_000)
        self._require_text(actor_ref, "actor_ref", 191)
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if blocked_until is not None:
            if blocked_until.tzinfo is None:
                raise ValueError("blocked_until must be timezone-aware")
            if blocked_until <= current:
                raise ValueError("blocked_until must be in the future")
        entry = self._repository.block_player(
            player_ref,
            reason,
            blocked_until,
            is_synthetic,
            actor_ref,
            current,
        )
        self._invalidate(self._player_key("blacklist", player_ref))
        return entry

    def unblock_player(self, player_ref: str, *, actor_ref: str) -> bool:
        self._require_text(player_ref, "player_ref", 191)
        self._require_text(actor_ref, "actor_ref", 191)
        removed = self._repository.unblock_player(player_ref, actor_ref, datetime.now(UTC))
        self._invalidate(self._player_key("blacklist", player_ref))
        return removed

    def player_risk_count(self, player_ref: str, *, window_seconds: int = 3_600) -> int:
        self._require_text(player_ref, "player_ref", 191)
        if window_seconds < 1:
            raise ValueError("window_seconds must be positive")
        key = self._player_key(f"risk-count:{window_seconds}", player_ref)
        cached = self._read(key)
        if cached is not None:
            count = cached.get("count")
            if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                return count
            self._logger.warning("invalid_risk_counter_cache", cache_key=key)
        now = datetime.now(UTC)
        count = self._repository.player_risk_count(
            player_ref, now - timedelta(seconds=window_seconds)
        )
        self._write(key, {"count": count}, window_seconds)
        return count

    def check_rate_limit(
        self,
        subject: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        self._require_text(subject, "subject", 191)
        if limit < 1 or window_seconds < 1:
            raise ValueError("rate limit and window must be positive")
        if not isinstance(self._cache, BusinessCachePort):
            raise TypeError("cache does not support atomic rate limiting")
        key = self._player_key(f"rate-limit:{limit}:{window_seconds}", subject)
        count, retry_after = self._cache.consume_rate_limit(key, limit, window_seconds)
        return RateLimitDecision(
            allowed=count <= limit,
            count=count,
            retry_after_seconds=retry_after,
            limit=limit,
            window_seconds=window_seconds,
        )

    def _read(self, key: str) -> dict[str, Any] | None:
        try:
            raw = self._cache.get(key)
        except RedisError as error:
            self._logger.warning("cache_read_unavailable", cache_key=key, error=str(error))
            return None
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            self._logger.warning("cache_payload_invalid", cache_key=key)
            return None
        if not isinstance(value, dict):
            self._logger.warning("cache_payload_invalid", cache_key=key)
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
            self._logger.warning("cache_write_unavailable", cache_key=key, error=str(error))

    def _invalidate(self, key: str) -> None:
        try:
            self._cache.delete(key)
        except RedisError as error:
            self._logger.warning("cache_invalidation_failed", cache_key=key, error=str(error))

    @staticmethod
    def _require_text(value: str, name: str, max_length: int) -> None:
        if not isinstance(value, str) or not value.strip() or len(value) > max_length:
            raise ValueError(
                f"{name} must be a non-empty string of at most {max_length} characters"
            )

    @staticmethod
    def _configuration_key(kind: str, scope: str) -> str:
        digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()
        return f"claro:cache:v1:{kind}:{digest}"

    @staticmethod
    def _player_key(kind: str, player_ref: str) -> str:
        digest = hashlib.sha256(player_ref.encode("utf-8")).hexdigest()
        return f"claro:cache:v1:{kind}:{digest}"


def _serialize_blacklist_entry(entry: BlacklistEntry | None) -> dict[str, Any] | None:
    if entry is None:
        return None
    return {
        "id": str(entry.id),
        "player_ref": entry.player_ref,
        "reason": entry.reason,
        "blocked_until": entry.blocked_until.isoformat() if entry.blocked_until else None,
        "is_synthetic": entry.is_synthetic,
    }
