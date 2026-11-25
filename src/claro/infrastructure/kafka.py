from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import structlog
from confluent_kafka import Consumer as KafkaClientConsumer
from confluent_kafka import (
    ConsumerGroupTopicPartitions,
    KafkaError,
    KafkaException,
    Producer,
    TopicPartition,
)
from confluent_kafka.admin import AdminClient, NewTopic

from claro.application.events import EventEnvelope
from claro.application.message_events import (
    MessageSerializationError,
    decode_event,
    encode_event,
)
from claro.application.message_processing import (
    ERROR_CODE_HEADER,
    ERROR_DETAIL_HEADER,
    ORIGIN_OFFSET_HEADER,
    ORIGIN_PARTITION_HEADER,
    ORIGIN_RECEIVED_AT_HEADER,
    ORIGIN_TOPIC_HEADER,
    RETRY_COUNT_HEADER,
    ConsumedMessage,
    HandlingResult,
    PermanentMessageError,
)
from claro.application.message_processing import (
    RetryableMessageError as RetryableMessageError,
)
from claro.application.ports import EventBusPort

logger = structlog.get_logger(__name__)


class KafkaDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class KafkaTopics:
    raw: str = "game.messages.raw"
    processed: str = "game.messages.processed"
    risk: str = "game.risk.events"
    moderation: str = "game.moderation.events"
    retry: str = "game.messages.retry"
    dead_letter: str = "game.messages.dead-letter"

    def all(self) -> tuple[str, ...]:
        return (
            self.raw,
            self.processed,
            self.risk,
            self.moderation,
            self.retry,
            self.dead_letter,
        )


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    event_id: UUID
    topic: str
    partition: int
    offset: int
    sent_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "topic": self.topic,
            "partition": self.partition,
            "offset": self.offset,
            "sent_at": self.sent_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ConsumerMetrics:
    consumed: int = 0
    processed: int = 0
    duplicates: int = 0
    failed: int = 0
    retried: int = 0
    dead_lettered: int = 0
    routing_failures: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "consumed": self.consumed,
            "processed": self.processed,
            "duplicates": self.duplicates,
            "failed": self.failed,
            "retried": self.retried,
            "dead_lettered": self.dead_lettered,
            "routing_failures": self.routing_failures,
        }


@dataclass(frozen=True, slots=True)
class PartitionLag:
    topic: str
    partition: int
    committed_offset: int | None
    high_watermark: int
    lag: int | None


@dataclass(frozen=True, slots=True)
class ConsumerGroupStatus:
    group_id: str
    state: str
    members: int
    partitions: tuple[PartitionLag, ...]
    total_lag: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "state": self.state,
            "members": self.members,
            "total_lag": self.total_lag,
            "partitions": [
                {
                    "topic": item.topic,
                    "partition": item.partition,
                    "committed_offset": item.committed_offset,
                    "high_watermark": item.high_watermark,
                    "lag": item.lag,
                }
                for item in self.partitions
            ],
        }


class KafkaEventBus(EventBusPort):
    transport = "kafka"

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        client_id: str,
        security_protocol: str = "PLAINTEXT",
    ) -> None:
        self._topic = topic
        self._config: dict[str, Any] = {
            "bootstrap.servers": bootstrap_servers,
            "client.id": client_id,
            "security.protocol": security_protocol,
        }
        self._producer = Producer(
            {
                **self._config,
                "acks": "all",
                "enable.idempotence": True,
                "message.timeout.ms": 10000,
            }
        )

    def publish(self, event: EventEnvelope) -> None:
        delivery_errors: list[KafkaError] = []

        def on_delivery(error: KafkaError | None, _message: Any) -> None:
            if error is not None:
                delivery_errors.append(error)

        self._producer.produce(
            self._topic,
            key=str(event.event_id),
            value=encode_event(event),
            on_delivery=on_delivery,
        )
        remaining = self._producer.flush(10)
        if remaining:
            raise TimeoutError(f"Kafka delivery timed out with {remaining} message(s) pending")
        if delivery_errors:
            raise KafkaException(delivery_errors[0])

    def check(self) -> None:
        AdminClient(self._config).list_topics(timeout=3)

    def ensure_topic(self, partitions: int = 1, replication_factor: int = 1) -> None:
        KafkaAdmin(
            self._config["bootstrap.servers"],
            client_id=self._config["client.id"],
            security_protocol=self._config["security.protocol"],
        ).ensure_topics([self._topic], partitions, replication_factor)

    def consume_one(
        self, event_id: str, group_id: str, timeout_seconds: float = 15.0
    ) -> EventEnvelope:
        consumer = KafkaClientConsumer(
            {
                **self._config,
                "group.id": group_id,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }
        )
        try:
            consumer.subscribe([self._topic])
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                message = consumer.poll(1.0)
                if message is None:
                    continue
                if message.error():
                    raise KafkaException(message.error())
                event = decode_event(message.value())
                if str(event.event_id) == event_id:
                    consumer.commit(message=message, asynchronous=False)
                    return event
            raise TimeoutError(f"Kafka event {event_id} was not received before timeout")
        finally:
            consumer.close()

    def close(self) -> None:
        remaining = self._producer.flush(5)
        if remaining:
            raise TimeoutError(f"Kafka shutdown timed out with {remaining} message(s) pending")


class KafkaAdmin:
    def __init__(
        self,
        bootstrap_servers: str,
        client_id: str = "claro-admin",
        security_protocol: str = "PLAINTEXT",
    ) -> None:
        self._config: dict[str, Any] = {
            "bootstrap.servers": bootstrap_servers,
            "client.id": client_id,
            "security.protocol": security_protocol,
        }
        self._admin = AdminClient(self._config)

    def ensure_topics(
        self,
        topics: Sequence[str],
        partitions: int = 3,
        replication_factor: int = 1,
    ) -> tuple[str, ...]:
        requested = tuple(dict.fromkeys(topics))
        futures = self._admin.create_topics(
            [
                NewTopic(name, num_partitions=partitions, replication_factor=replication_factor)
                for name in requested
            ]
        )
        for topic, future in futures.items():
            try:
                future.result(timeout=10)
            except KafkaException as error:
                kafka_error = error.args[0]
                if kafka_error.code() != KafkaError.TOPIC_ALREADY_EXISTS:
                    raise
                logger.info("kafka_topic_already_exists", topic=topic)
            else:
                logger.info("kafka_topic_created", topic=topic)
        return requested

    def list_topics(self) -> dict[str, Any]:
        metadata = self._admin.list_topics(timeout=10)
        return {
            topic: {
                "partitions": len(item.partitions),
                "replication_factor": (len(item.partitions[0].replicas) if item.partitions else 0),
            }
            for topic, item in sorted(metadata.topics.items())
            if not topic.startswith("__")
        }

    def check(self) -> None:
        self._admin.list_topics(timeout=3)

    def consumer_group_status(self, group_id: str) -> ConsumerGroupStatus:
        description_future = self._admin.describe_consumer_groups([group_id])[group_id]
        try:
            description = description_future.result(timeout=10)
        except KafkaException as error:
            kafka_error = error.args[0]
            if kafka_error.code() == getattr(KafkaError, "GROUP_ID_NOT_FOUND", -1):
                return ConsumerGroupStatus(group_id, "not_found", 0, (), None)
            raise

        request = ConsumerGroupTopicPartitions(group_id)
        offsets_future = self._admin.list_consumer_group_offsets([request])[group_id]
        try:
            offsets = offsets_future.result(timeout=10)
        except KafkaException as error:
            kafka_error = error.args[0]
            if kafka_error.code() == getattr(KafkaError, "GROUP_ID_NOT_FOUND", -1):
                return ConsumerGroupStatus(
                    group_id,
                    str(description.state),
                    len(description.members),
                    (),
                    None,
                )
            raise

        lag_items: list[PartitionLag] = []
        watermarks = KafkaClientConsumer(
            {
                **self._config,
                "group.id": f"{group_id}-lag-inspector-{time.time_ns()}",
                "enable.auto.commit": False,
            }
        )
        try:
            for partition in offsets.topic_partitions:
                committed = partition.offset
                low, high = watermarks.get_watermark_offsets(partition, timeout=10)
                valid = committed >= 0
                lag_items.append(
                    PartitionLag(
                        topic=partition.topic,
                        partition=partition.partition,
                        committed_offset=committed if valid else None,
                        high_watermark=high,
                        lag=max(0, high - max(low, committed)) if valid else high - low,
                    )
                )
        finally:
            watermarks.close()
        total_lag = (
            sum(item.lag or 0 for item in lag_items)
            if lag_items and all(item.lag is not None for item in lag_items)
            else None
        )
        return ConsumerGroupStatus(
            group_id=group_id,
            state=str(description.state),
            members=len(description.members),
            partitions=tuple(lag_items),
            total_lag=total_lag,
        )


class KafkaProducer:
    def __init__(
        self,
        bootstrap_servers: str,
        client_id: str,
        security_protocol: str = "PLAINTEXT",
        timeout_ms: int = 10_000,
    ) -> None:
        self._timeout_seconds = timeout_ms / 1000
        self._deliveries: list[DeliveryRecord] = []
        self._errors: list[KafkaError] = []
        self._closed = False
        self._producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "client.id": client_id,
                "security.protocol": security_protocol,
                "acks": "all",
                "enable.idempotence": True,
                "message.timeout.ms": timeout_ms,
                "request.timeout.ms": min(timeout_ms, 30_000),
                "retry.backoff.ms": 100,
            }
        )

    def produce(
        self,
        topic: str,
        event: EventEnvelope,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if self._closed:
            raise RuntimeError("producer is closed")
        value = encode_event(event)
        kafka_headers = [(key, value.encode("utf-8")) for key, value in (headers or {}).items()]
        deadline = time.monotonic() + self._timeout_seconds
        while True:
            try:
                self._producer.produce(
                    topic,
                    key=str(event.event_id),
                    value=value,
                    headers=kafka_headers,
                    on_delivery=lambda error, message, event_id=event.event_id: self._on_delivery(
                        event_id, error, message
                    ),
                )
                self._producer.poll(0)
                return
            except BufferError as error:
                if time.monotonic() >= deadline:
                    raise KafkaDeliveryError("Kafka producer queue remained full") from error
                self._producer.poll(0.1)

    def publish(
        self,
        topic: str,
        event: EventEnvelope,
        headers: Mapping[str, str] | None = None,
    ) -> DeliveryRecord:
        before = len(self._deliveries)
        self.produce(topic, event, headers)
        self.flush()
        if len(self._deliveries) != before + 1:
            raise KafkaDeliveryError("Kafka delivery callback was not received")
        return self._deliveries[-1]

    def publish_many(
        self,
        events: Sequence[tuple[str, EventEnvelope, Mapping[str, str] | None]],
    ) -> list[DeliveryRecord]:
        before = len(self._deliveries)
        for topic, event, headers in events:
            self.produce(topic, event, headers)
        self.flush()
        delivered = self._deliveries[before:]
        if len(delivered) != len(events):
            raise KafkaDeliveryError(
                f"expected {len(events)} delivery callbacks, received {len(delivered)}"
            )
        return delivered

    def flush(self) -> None:
        remaining = self._producer.flush(self._timeout_seconds)
        if remaining:
            raise KafkaDeliveryError(f"Kafka delivery timed out with {remaining} pending")
        if self._errors:
            raise KafkaException(self._errors[0])

    def close(self) -> None:
        if not self._closed:
            self.flush()
            self._closed = True

    def _on_delivery(self, event_id: UUID, error: KafkaError | None, message: Any) -> None:
        if error is not None:
            self._errors.append(error)
            return
        self._deliveries.append(
            DeliveryRecord(
                event_id=event_id,
                topic=message.topic(),
                partition=message.partition(),
                offset=message.offset(),
                sent_at=datetime.now(UTC),
            )
        )


class KafkaConsumer:
    def __init__(
        self,
        bootstrap_servers: str,
        topics: Sequence[str],
        group_id: str,
        client_id: str,
        retry_topic: str,
        dead_letter_topic: str,
        security_protocol: str = "PLAINTEXT",
        max_retries: int = 3,
        poll_timeout_seconds: float = 1.0,
        timeout_ms: int = 10_000,
        auto_offset_reset: Literal["earliest", "latest"] = "earliest",
    ) -> None:
        if not topics:
            raise ValueError("at least one Kafka topic is required")
        if auto_offset_reset not in {"earliest", "latest"}:
            raise ValueError("auto_offset_reset must be earliest or latest")
        self._consumer = KafkaClientConsumer(
            {
                "bootstrap.servers": bootstrap_servers,
                "client.id": client_id,
                "group.id": group_id,
                "security.protocol": security_protocol,
                "auto.offset.reset": auto_offset_reset,
                "enable.auto.commit": False,
                "enable.auto.offset.store": False,
            }
        )
        self._routing_producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "client.id": f"{client_id}-router",
                "security.protocol": security_protocol,
                "acks": "all",
                "enable.idempotence": True,
                "message.timeout.ms": timeout_ms,
            }
        )
        self._group_id = group_id
        self._topics = tuple(topics)
        self._retry_topic = retry_topic
        self._dead_letter_topic = dead_letter_topic
        self._max_retries = max_retries
        self._poll_timeout = poll_timeout_seconds
        self._route_timeout = timeout_ms / 1000
        self._closed = False
        self._counts = {name: 0 for name in ConsumerMetrics.__dataclass_fields__}

    @property
    def metrics(self) -> ConsumerMetrics:
        return ConsumerMetrics(**self._counts)

    def run(
        self,
        handler: Callable[[ConsumedMessage], HandlingResult | None],
        max_messages: int | None = None,
        idle_timeout_seconds: float | None = None,
    ) -> ConsumerMetrics:
        if max_messages is not None and max_messages < 1:
            raise ValueError("max_messages must be positive")
        if idle_timeout_seconds is not None and idle_timeout_seconds <= 0:
            raise ValueError("idle_timeout_seconds must be positive")
        self._consumer.subscribe(list(self._topics))
        last_message_at = time.monotonic()
        while max_messages is None or self._counts["consumed"] < max_messages:
            if (
                idle_timeout_seconds is not None
                and time.monotonic() - last_message_at >= idle_timeout_seconds
            ):
                break
            message = self._consumer.poll(self._poll_timeout)
            if message is None:
                continue
            last_message_at = time.monotonic()
            self._counts["consumed"] += 1
            if message.error():
                if message.error().code() == KafkaError._PARTITION_EOF:
                    continue
                raise KafkaException(message.error())
            try:
                event = decode_event(message.value())
            except MessageSerializationError as error:
                self._handle_failure(message, None, error, permanent=True)
                continue

            consumed = ConsumedMessage(
                event=event,
                topic=message.topic(),
                partition=message.partition(),
                offset=message.offset(),
                received_at=datetime.now(UTC),
                headers={
                    key: value.decode("utf-8") if isinstance(value, bytes) else str(value)
                    for key, value in (message.headers() or [])
                    if value is not None
                },
            )
            try:
                result = handler(consumed) or HandlingResult()
            except PermanentMessageError as error:
                self._handle_failure(message, consumed, error, permanent=True)
                continue
            except MessageSerializationError as error:
                self._handle_failure(message, consumed, error, permanent=True)
                continue
            except Exception as error:
                self._handle_failure(message, consumed, error, permanent=False)
                continue
            if result.status == "duplicate":
                self._counts["duplicates"] += 1
            else:
                self._counts["processed"] += 1
            self._consumer.commit(message=message, asynchronous=False)
            logger.debug(
                "kafka_message_processed",
                group_id=self._group_id,
                event_id=str(event.event_id),
                topic=consumed.topic,
                partition=consumed.partition,
                offset=consumed.offset,
                status=result.status,
            )
        return self.metrics

    def close(self) -> None:
        if not self._closed:
            self._consumer.close()
            remaining = self._routing_producer.flush(self._route_timeout)
            if remaining:
                raise KafkaDeliveryError(
                    f"Kafka router shutdown timed out with {remaining} pending"
                )
            self._closed = True

    def _handle_failure(
        self,
        message: Any,
        consumed: ConsumedMessage | None,
        error: Exception,
        permanent: bool,
    ) -> None:
        self._counts["failed"] += 1
        retry_count = consumed.retry_count if consumed else 0
        should_retry = not permanent and retry_count < self._max_retries
        route_topic = self._retry_topic if should_retry else self._dead_letter_topic
        headers = {
            ORIGIN_TOPIC_HEADER: message.topic(),
            ORIGIN_PARTITION_HEADER: str(message.partition()),
            ORIGIN_OFFSET_HEADER: str(message.offset()),
            ORIGIN_RECEIVED_AT_HEADER: (
                consumed.received_at.isoformat() if consumed else datetime.now(UTC).isoformat()
            ),
            ERROR_CODE_HEADER: type(error).__name__,
            ERROR_DETAIL_HEADER: str(error)[:1_000],
            RETRY_COUNT_HEADER: str(retry_count + 1 if should_retry else retry_count),
        }
        try:
            self._route(message, route_topic, headers)
        except Exception:
            self._counts["routing_failures"] += 1
            self._consumer.seek(
                TopicPartition(message.topic(), message.partition(), message.offset())
            )
            raise
        if should_retry:
            self._counts["retried"] += 1
        else:
            self._counts["dead_lettered"] += 1
        self._consumer.commit(message=message, asynchronous=False)
        logger.warning(
            "kafka_message_routed",
            group_id=self._group_id,
            topic=message.topic(),
            partition=message.partition(),
            offset=message.offset(),
            route_topic=route_topic,
            retry_count=retry_count,
            error_code=type(error).__name__,
        )

    def _route(self, message: Any, topic: str, headers: Mapping[str, str]) -> None:
        delivery_errors: list[KafkaError] = []

        def on_delivery(error: KafkaError | None, _delivered: Any) -> None:
            if error is not None:
                delivery_errors.append(error)

        self._routing_producer.produce(
            topic,
            key=message.key(),
            value=message.value(),
            headers=[(key, value.encode("utf-8")) for key, value in headers.items()],
            on_delivery=on_delivery,
        )
        remaining = self._routing_producer.flush(self._route_timeout)
        if remaining:
            raise KafkaDeliveryError(f"retry routing timed out with {remaining} pending")
        if delivery_errors:
            raise KafkaException(delivery_errors[0])
