from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class BlacklistEntry:
    id: UUID
    player_ref: str
    reason: str
    blocked_until: datetime | None
    is_synthetic: bool

    def is_active(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        return self.blocked_until is None or self.blocked_until > current


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    count: int
    retry_after_seconds: int
    limit: int
    window_seconds: int
