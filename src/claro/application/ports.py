from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from claro.application.events import EventEnvelope
from claro.domain.message import Message
from claro.domain.safety import BlacklistEntry


class EventBusPort(Protocol):
    def publish(self, event: EventEnvelope) -> None: ...

    def check(self) -> None: ...

    def close(self) -> None: ...


class CachePort(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None: ...

    def increment(self, key: str, amount: int = 1) -> int: ...

    def delete(self, key: str) -> None: ...

    def check(self) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class BusinessCachePort(Protocol):
    def consume_rate_limit(self, key: str, limit: int, window_seconds: int) -> tuple[int, int]: ...


class SafetyRepositoryPort(Protocol):
    def sensitive_words(self, dataset_id: UUID | None, now: datetime) -> tuple[str, ...]: ...

    def active_policy(
        self, policy_key: str, dataset_id: UUID | None, now: datetime
    ) -> dict[str, Any] | None: ...

    def blacklist_entry(self, player_ref: str) -> BlacklistEntry | None: ...

    def block_player(
        self,
        player_ref: str,
        reason: str,
        blocked_until: datetime | None,
        is_synthetic: bool,
        actor_ref: str,
        now: datetime,
    ) -> BlacklistEntry: ...

    def unblock_player(self, player_ref: str, actor_ref: str, now: datetime) -> bool: ...

    def player_risk_count(self, player_ref: str, since: datetime) -> int: ...


class MessageRepository(Protocol):
    def add(self, message: Message) -> None: ...

    def get(self, message_id: UUID) -> Message | None: ...

    def get_by_external_id(self, external_message_id: str) -> Message | None: ...

    def list_recent(self, limit: int = 20) -> Sequence[Message]: ...
