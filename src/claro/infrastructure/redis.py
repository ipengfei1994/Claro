from __future__ import annotations

from redis import Redis

from claro.application.ports import BusinessCachePort, CachePort

_RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return {current, redis.call('TTL', KEYS[1])}
"""


class RedisCacheAdapter(CachePort, BusinessCachePort):
    def __init__(self, url: str, socket_timeout: float = 3.0) -> None:
        self._client = Redis.from_url(
            url,
            decode_responses=True,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_timeout,
        )

    def get(self, key: str) -> str | None:
        return self._client.get(key)

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        self._client.set(key, value, ex=ttl_seconds)

    def increment(self, key: str, amount: int = 1) -> int:
        return int(self._client.incrby(key, amount))

    def consume_rate_limit(self, key: str, limit: int, window_seconds: int) -> tuple[int, int]:
        if limit < 1 or window_seconds < 1:
            raise ValueError("rate limit and window must be positive")
        count, retry_after = self._client.eval(_RATE_LIMIT_SCRIPT, 1, key, window_seconds)
        return int(count), max(0, int(retry_after))

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def ttl(self, key: str) -> int:
        return int(self._client.ttl(key))

    def check(self) -> None:
        if not self._client.ping():
            raise RuntimeError("Redis PING returned false")

    def close(self) -> None:
        self._client.close()
