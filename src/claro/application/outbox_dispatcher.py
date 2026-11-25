from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

import structlog

from claro.application.events import EventEnvelope
from claro.data_access.repositories.governance_repository import GovernanceRepository

GovernanceHeaders = Mapping[str, str]


class OutboxPublisher(Protocol):
    def publish(
        self, topic: str, event: EventEnvelope, headers: GovernanceHeaders | None = None
    ) -> Any: ...


class OutboxDispatcher:
    """Reliably publish governance outbox events to Kafka.

    Business transactions never publish to Kafka directly: they append an
    ``outbox_event`` row inside the same database transaction. This dispatcher
    then reads those rows and publishes them, which keeps the persistent state
    and the event stream consistent without a distributed transaction. Accepted
    events are marked published; failures are retried with backoff until the
    attempt budget is exhausted. ``dedupe_key`` makes delivery idempotent, so a
    duplicate publish is harmless for consumers that key on the event id.
    """

    def __init__(
        self,
        repository: GovernanceRepository,
        publisher: OutboxPublisher,
        *,
        batch_size: int = 100,
        max_attempts: int = 5,
        retry_delay_seconds: int = 30,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if retry_delay_seconds < 1:
            raise ValueError("retry_delay_seconds must be positive")
        self._repository = repository
        self._publisher = publisher
        self._batch_size = batch_size
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay_seconds
        self._logger = structlog.get_logger(__name__)

    def dispatch_once(self) -> dict[str, int]:
        events = self._repository.pending_outbox(
            limit=self._batch_size, max_attempts=self._max_attempts
        )
        published = 0
        failed = 0
        for event in events:
            envelope = _to_envelope(event)
            try:
                self._publisher.publish(
                    str(event["topic"]), envelope, _string_headers(event.get("headers") or {})
                )
            except Exception as error:  # noqa: BLE001 - any transport error must retry
                failed += 1
                self._logger.warning(
                    "outbox_publish_failed",
                    event_id=event["id"],
                    event_type=event["event_type"],
                    error=str(error),
                )
                self._repository.mark_outbox_failed(
                    UUID(str(event["id"])),
                    error=str(error),
                    retry_delay_seconds=self._retry_delay,
                )
            else:
                published += 1
                self._repository.mark_outbox_published(UUID(str(event["id"])))
        return {"fetched": len(events), "published": published, "failed": failed}

    def dispatch_all(self, *, max_batches: int = 100) -> dict[str, int]:
        total = {"batches": 0, "fetched": 0, "published": 0, "failed": 0}
        for _ in range(max_batches):
            result = self.dispatch_once()
            total["batches"] += 1
            total["fetched"] += result["fetched"]
            total["published"] += result["published"]
            total["failed"] += result["failed"]
            if result["fetched"] == 0 or result["failed"] > 0:
                break
        return total


def _to_envelope(event: dict[str, Any]) -> EventEnvelope:
    occurred_at = datetime.now(UTC)
    raw_created = event.get("created_at")
    if raw_created:
        try:
            parsed = datetime.fromisoformat(str(raw_created))
            occurred_at = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            occurred_at = datetime.now(UTC)
    return EventEnvelope(
        event_id=UUID(str(event["id"])),
        event_type=str(event["event_type"]),
        payload=dict(event.get("payload") or {}),
        occurred_at=occurred_at,
    )


def _string_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    return {str(key): str(value) for key, value in headers.items()}
