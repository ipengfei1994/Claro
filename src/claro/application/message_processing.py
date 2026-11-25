from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from claro.application.events import EventEnvelope

RETRY_COUNT_HEADER = "x-claro-retry-count"
ORIGIN_TOPIC_HEADER = "x-claro-origin-topic"
ORIGIN_PARTITION_HEADER = "x-claro-origin-partition"
ORIGIN_OFFSET_HEADER = "x-claro-origin-offset"
ORIGIN_RECEIVED_AT_HEADER = "x-claro-origin-received-at"
ERROR_CODE_HEADER = "x-claro-error-code"
ERROR_DETAIL_HEADER = "x-claro-error-detail"


class MessageProcessingError(Exception):
    pass


class RetryableMessageError(MessageProcessingError):
    pass


class PermanentMessageError(MessageProcessingError):
    pass


@dataclass(frozen=True, slots=True)
class ConsumedMessage:
    event: EventEnvelope
    topic: str
    partition: int
    offset: int
    received_at: datetime
    headers: Mapping[str, str]

    @property
    def retry_count(self) -> int:
        try:
            return max(0, int(self.headers.get(RETRY_COUNT_HEADER, "0")))
        except ValueError:
            return 0

    @property
    def source_topic(self) -> str:
        return self.headers.get(ORIGIN_TOPIC_HEADER, self.topic)

    @property
    def source_partition(self) -> int:
        try:
            return int(self.headers.get(ORIGIN_PARTITION_HEADER, self.partition))
        except ValueError:
            return self.partition

    @property
    def source_offset(self) -> int:
        try:
            return int(self.headers.get(ORIGIN_OFFSET_HEADER, self.offset))
        except ValueError:
            return self.offset

    @property
    def source_received_at(self) -> datetime:
        value = self.headers.get(ORIGIN_RECEIVED_AT_HEADER)
        if value:
            try:
                parsed = datetime.fromisoformat(value)
                if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                    return parsed
            except ValueError:
                pass
        return self.received_at


@dataclass(frozen=True, slots=True)
class HandlingResult:
    status: Literal["processed", "duplicate"] = "processed"
