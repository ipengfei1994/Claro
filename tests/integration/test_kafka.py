from __future__ import annotations

from uuid import uuid4

import pytest

from claro.application.events import EventEnvelope
from claro.bootstrap import AppContainer
from claro.config.settings import load_settings
from claro.infrastructure.kafka import (
    ERROR_CODE_HEADER,
    ORIGIN_RECEIVED_AT_HEADER,
    RETRY_COUNT_HEADER,
    HandlingResult,
    KafkaAdmin,
    KafkaConsumer,
    KafkaEventBus,
    KafkaProducer,
    PermanentMessageError,
    RetryableMessageError,
)


@pytest.mark.integration
def test_kafka_produce_consume_round_trip(full_container: AppContainer) -> None:
    bus = full_container.event_bus
    assert isinstance(bus, KafkaEventBus)
    bus.ensure_topic()
    event = EventEnvelope(
        event_type="claro.integration.check",
        payload={"synthetic": True},
        trace_id=uuid4().hex,
    )
    bus.publish(event)
    received = bus.consume_one(str(event.event_id), f"claro-integration-{uuid4()}")
    assert received.event_id == event.event_id
    assert received.event_type == event.event_type
    assert received.payload == event.payload


@pytest.mark.integration
def test_kafka_retry_dlq_manual_commit_and_group_lag(full_container: AppContainer) -> None:
    settings = load_settings()
    kafka = settings.kafka
    suffix = uuid4().hex[:12]
    raw_topic = f"claro.test.raw.{suffix}"
    retry_topic = f"claro.test.retry.{suffix}"
    dlq_topic = f"claro.test.dlq.{suffix}"
    raw_group = f"claro-test-raw-{suffix}"
    retry_group = f"claro-test-retry-{suffix}"
    dlq_group = f"claro-test-dlq-{suffix}"
    admin = KafkaAdmin(kafka.bootstrap_servers, "claro-integration-admin")
    topics = [raw_topic, retry_topic, dlq_topic]
    admin.ensure_topics(topics, partitions=1, replication_factor=1)
    producer = KafkaProducer(kafka.bootstrap_servers, f"claro-test-producer-{suffix}")
    received_at = []

    def make_consumer(topic: str, group_id: str) -> KafkaConsumer:
        return KafkaConsumer(
            kafka.bootstrap_servers,
            [topic],
            group_id,
            f"claro-test-consumer-{suffix}",
            retry_topic,
            dlq_topic,
            kafka.security_protocol,
            kafka.max_retries,
            0.2,
        )

    try:
        first = EventEnvelope(event_type="synthetic.retry.test", payload={"attempt": 1})
        delivery = producer.publish(raw_topic, first)

        def fail_once(message) -> None:
            received_at.append(message.received_at)
            raise RetryableMessageError("temporary integration failure")

        raw_consumer = make_consumer(raw_topic, raw_group)
        try:
            routed = raw_consumer.run(fail_once, max_messages=1)
        finally:
            raw_consumer.close()
        assert routed.retried == 1
        assert received_at[0] >= delivery.sent_at

        retry_consumer = make_consumer(retry_topic, retry_group)
        try:
            retried = retry_consumer.run(lambda _message: HandlingResult(), max_messages=1)
        finally:
            retry_consumer.close()
        assert retried.processed == 1

        second = EventEnvelope(event_type="synthetic.dlq.test", payload={"attempt": 2})
        producer.publish(raw_topic, second)

        def fail_permanently(_message) -> None:
            raise PermanentMessageError("permanent integration failure")

        raw_consumer = make_consumer(raw_topic, raw_group)
        try:
            rejected = raw_consumer.run(fail_permanently, max_messages=1)
        finally:
            raw_consumer.close()
        assert rejected.dead_lettered == 1

        dead_letters = []

        def capture_dead_letter(message) -> HandlingResult:
            dead_letters.append(message)
            return HandlingResult()

        dlq_consumer = make_consumer(dlq_topic, dlq_group)
        try:
            consumed = dlq_consumer.run(capture_dead_letter, max_messages=1)
        finally:
            dlq_consumer.close()
        assert consumed.processed == 1
        assert dead_letters[0].event.event_id == second.event_id
        assert dead_letters[0].headers[ERROR_CODE_HEADER] == "PermanentMessageError"
        assert dead_letters[0].headers[ORIGIN_RECEIVED_AT_HEADER]
        assert RETRY_COUNT_HEADER in dead_letters[0].headers

        status = admin.consumer_group_status(raw_group)
        assert status.total_lag == 0
        assert len(status.partitions) == 1
        assert status.partitions[0].committed_offset == 2
    finally:
        producer.close()
