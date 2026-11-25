from __future__ import annotations

from uuid import uuid4

import pytest

from claro.bootstrap import AppContainer


@pytest.mark.integration
def test_redis_round_trip(full_container: AppContainer) -> None:
    cache = full_container.cache
    assert cache is not None
    key = f"claro:integration:{uuid4()}"
    try:
        cache.set(key, "connected", ttl_seconds=30)
        assert cache.get(key) == "connected"
        assert cache.increment(f"{key}:counter") == 1
    finally:
        cache.delete(key)
        cache.delete(f"{key}:counter")
