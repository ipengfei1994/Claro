from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from claro.application.safety_cache import SafetyCacheService
from claro.domain.safety import BlacklistEntry


class FakeCache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}
        self.deleted: list[str] = []
        self.rate_counts: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        self.values[key] = value
        self.ttls[key] = ttl_seconds

    def increment(self, key: str, amount: int = 1) -> int:
        value = int(self.values.get(key, "0")) + amount
        self.values[key] = str(value)
        return value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.deleted.append(key)

    def check(self) -> None:
        return None

    def close(self) -> None:
        return None

    def consume_rate_limit(self, key: str, limit: int, window_seconds: int) -> tuple[int, int]:
        count = self.rate_counts.get(key, 0) + 1
        self.rate_counts[key] = count
        return count, window_seconds if count == 1 else max(1, window_seconds - 1)


class FakeRepository:
    def __init__(self) -> None:
        self.words = ("赠金币", "代充")
        self.policy: dict[str, Any] | None = {"version": 1, "definition": {"allow": True}}
        self.entry: BlacklistEntry | None = None
        self.sensitive_calls = 0
        self.policy_calls = 0
        self.blacklist_calls = 0
        self.risk_count = 7
        self.risk_calls = 0

    def sensitive_words(self, dataset_id, now) -> tuple[str, ...]:
        self.sensitive_calls += 1
        return self.words

    def active_policy(self, policy_key, dataset_id, now) -> dict[str, Any] | None:
        self.policy_calls += 1
        return self.policy

    def blacklist_entry(self, player_ref: str) -> BlacklistEntry | None:
        self.blacklist_calls += 1
        return self.entry

    def block_player(self, player_ref, reason, blocked_until, is_synthetic, actor_ref, now):
        self.entry = BlacklistEntry(uuid4(), player_ref, reason, blocked_until, is_synthetic)
        return self.entry

    def unblock_player(self, player_ref, actor_ref, now) -> bool:
        removed = self.entry is not None
        self.entry = None
        return removed

    def player_risk_count(self, player_ref, since) -> int:
        self.risk_calls += 1
        return self.risk_count


@pytest.fixture
def cache_service() -> tuple[SafetyCacheService, FakeCache, FakeRepository]:
    cache = FakeCache()
    repository = FakeRepository()
    return (
        SafetyCacheService(cache, repository, configuration_ttl_seconds=120),
        cache,
        repository,
    )


def test_sensitive_words_cache_hit_and_invalidation(
    cache_service: tuple[SafetyCacheService, FakeCache, FakeRepository],
) -> None:
    service, cache, repository = cache_service
    assert service.sensitive_words() == ("赠金币", "代充")
    assert service.sensitive_words() == ("赠金币", "代充")
    assert repository.sensitive_calls == 1
    assert 0 < next(iter(cache.ttls.values())) <= 120

    repository.words = ("新敏感词",)
    assert service.sensitive_words() == ("赠金币", "代充")
    service.invalidate_sensitive_words()
    assert service.sensitive_words() == ("新敏感词",)
    assert repository.sensitive_calls == 2


def test_policy_negative_cache_and_invalidation(
    cache_service: tuple[SafetyCacheService, FakeCache, FakeRepository],
) -> None:
    service, _, repository = cache_service
    repository.policy = None
    assert service.active_policy("missing") is None
    assert service.active_policy("missing") is None
    assert repository.policy_calls == 1

    repository.policy = {"version": 2, "definition": {"review": True}}
    service.invalidate_policy("missing")
    assert service.active_policy("missing") == repository.policy
    assert repository.policy_calls == 2


def test_blacklist_cache_and_expiration(
    cache_service: tuple[SafetyCacheService, FakeCache, FakeRepository],
) -> None:
    service, _, repository = cache_service
    now = datetime(2026, 11, 25, tzinfo=UTC)
    repository.entry = BlacklistEntry(
        uuid4(), "player-1", "synthetic abuse", now + timedelta(minutes=5), True
    )
    assert service.is_blacklisted("player-1", now)
    assert service.is_blacklisted("player-1", now + timedelta(minutes=1))
    assert repository.blacklist_calls == 1
    assert service.blacklist_entry("player-1", now + timedelta(minutes=6)) is None


def test_block_commits_before_cache_invalidation_and_unblocks(
    cache_service: tuple[SafetyCacheService, FakeCache, FakeRepository],
) -> None:
    service, cache, repository = cache_service
    now = datetime(2026, 11, 25, tzinfo=UTC)
    entry = service.block_player(
        "player-2", "synthetic abuse", is_synthetic=True, actor_ref="test", now=now
    )
    assert entry.player_ref == "player-2"
    assert repository.entry == entry
    assert cache.deleted
    assert service.is_blacklisted("player-2", now)
    assert service.unblock_player("player-2", actor_ref="test")
    assert not service.is_blacklisted("player-2", now)
    assert service.unblock_player("player-2", actor_ref="test") is False


def test_blacklist_rejects_expired_and_naive_deadlines(
    cache_service: tuple[SafetyCacheService, FakeCache, FakeRepository],
) -> None:
    service, _, _ = cache_service
    now = datetime(2026, 11, 25, tzinfo=UTC)
    with pytest.raises(ValueError, match="future"):
        service.block_player("player-2", "reason", blocked_until=now, actor_ref="test", now=now)
    with pytest.raises(ValueError, match="timezone-aware"):
        service.block_player(
            "player-2",
            "reason",
            blocked_until=now.replace(tzinfo=None),
            actor_ref="test",
            now=now,
        )


def test_player_risk_counter_uses_database_on_miss_then_cache(
    cache_service: tuple[SafetyCacheService, FakeCache, FakeRepository],
) -> None:
    service, _, repository = cache_service
    assert service.player_risk_count("player-3") == 7
    repository.risk_count = 9
    assert service.player_risk_count("player-3") == 7
    assert repository.risk_calls == 1
    assert service.player_risk_count("player-3", window_seconds=60) == 9
    assert repository.risk_calls == 2


def test_rate_limit_is_scoped_and_enforced(
    cache_service: tuple[SafetyCacheService, FakeCache, FakeRepository],
) -> None:
    service, _, _ = cache_service
    first = service.check_rate_limit("player-4", limit=2, window_seconds=60)
    second = service.check_rate_limit("player-4", limit=2, window_seconds=60)
    third = service.check_rate_limit("player-4", limit=2, window_seconds=60)
    other = service.check_rate_limit("player-5", limit=2, window_seconds=60)
    assert (first.allowed, second.allowed, third.allowed, other.allowed) == (
        True,
        True,
        False,
        True,
    )
    assert third.retry_after_seconds > 0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"limit": 0, "window_seconds": 60}, "positive"),
        ({"limit": 2, "window_seconds": 0}, "positive"),
    ],
)
def test_rate_limit_rejects_invalid_windows(
    cache_service: tuple[SafetyCacheService, FakeCache, FakeRepository],
    kwargs: dict[str, int],
    message: str,
) -> None:
    service, _, _ = cache_service
    with pytest.raises(ValueError, match=message):
        service.check_rate_limit("player", **kwargs)


def test_corrupt_cache_falls_back_to_database(
    cache_service: tuple[SafetyCacheService, FakeCache, FakeRepository],
) -> None:
    service, cache, repository = cache_service
    assert service.sensitive_words() == repository.words
    key = next(iter(cache.values))
    cache.values[key] = "not-json"
    assert service.sensitive_words() == repository.words
    assert repository.sensitive_calls == 2
