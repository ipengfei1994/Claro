from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from claro.application.events import EventEnvelope
from claro.application.message_events import decode_event, encode_event
from claro.infrastructure.kafka import (
    ERROR_CODE_HEADER,
    ORIGIN_TOPIC_HEADER,
    RETRY_COUNT_HEADER,
    HandlingResult,
    KafkaConsumer,
    KafkaDeliveryError,
    KafkaProducer,
    PermanentMessageError,
    RetryableMessageError,
)


class FakeMessage:
    def __init__(
        self,
        value: bytes,
        *,
        topic: str = "raw",
        partition: int = 0,
        offset: int = 1,
        headers: dict[str, bytes] | None = None,
    ) -> None:
        self._value = value
        self._topic = topic
        self._partition = partition
        self._offset = offset
        self._headers = headers or {}

    def value(self) -> bytes:
        return self._value

    def key(self) -> bytes:
        return b"key"

    def topic(self) -> str:
        return self._topic

    def partition(self) -> int:
        return self._partition

    def offset(self) -> int:
        return self._offset

    def headers(self) -> list[tuple[str, bytes]]:
        return list(self._headers.items())

    def error(self) -> None:
        return None


class FakeDeliveredMessage:
    def topic(self) -> str:
        return "raw"

    def partition(self) -> int:
        return 2

    def offset(self) -> int:
        return 7


class FakeConsumer:
    def __init__(self, messages: list[FakeMessage]) -> None:
        self.messages = list(messages)
        self.commits: list[FakeMessage] = []
        self.seeks: list[Any] = []
        self.subscriptions: list[list[str]] = []
        self.closed = False

    def subscribe(self, topics: list[str]) -> None:
        self.subscriptions.append(topics)

    def poll(self, _timeout: float) -> FakeMessage | None:
        return self.messages.pop(0) if self.messages else None

    def commit(self, *, message: FakeMessage, asynchronous: bool) -> None:
        assert asynchronous is False
        self.commits.append(message)

    def seek(self, partition: Any) -> None:
        self.seeks.append(partition)

    def close(self) -> None:
        self.closed = True


class FakeRoutingProducer:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.produced: list[dict[str, Any]] = []

    def produce(self, topic: str, **kwargs: Any) -> None:
        self.produced.append({"topic": topic, **kwargs})
        if self.fail:
            return
        kwargs["on_delivery"](None, FakeDeliveredMessage())

    def flush(self, _timeout: float) -> int:
        return 1 if self.fail else 0

    def poll(self, _timeout: float) -> None:
        return None


def _event() -> EventEnvelope:
    return EventEnvelope(
        event_type="synthetic.test",
        payload={"value": 1},
        trace_id=uuid4().hex,
    )


def _consumer(
    monkeypatch: pytest.MonkeyPatch,
    messages: list[FakeMessage],
    *,
    routing_producer: FakeRoutingProducer | None = None,
    max_retries: int = 3,
) -> tuple[KafkaConsumer, FakeConsumer, FakeRoutingProducer]:
    consumer = FakeConsumer(messages)
    router = routing_producer or FakeRoutingProducer()
    monkeypatch.setattr("claro.infrastructure.kafka.KafkaClientConsumer", lambda _config: consumer)
    monkeypatch.setattr("claro.infrastructure.kafka.Producer", lambda _config: router)
    instance = KafkaConsumer(
        "localhost:9092",
        ["raw"],
        "test-group",
        "test-client",
        "retry",
        "dlq",
        max_retries=max_retries,
    )
    return instance, consumer, router


def test_producer_batch_returns_real_delivery_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    producer = FakeRoutingProducer()
    monkeypatch.setattr("claro.infrastructure.kafka.Producer", lambda _config: producer)
    instance = KafkaProducer("localhost:9092", "test-producer")
    events = [("raw", _event(), None), ("raw", _event(), {"source": "test"})]

    deliveries = instance.publish_many(events)
    instance.close()

    assert len(deliveries) == 2
    assert {item.partition for item in deliveries} == {2}
    assert {item.offset for item in deliveries} == {7}
    assert decode_event(producer.produced[0]["value"]).event_id == events[0][1].event_id
    assert producer.produced[1]["headers"] == [("source", b"test")]


def test_retryable_failure_routes_to_retry_before_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    message = FakeMessage(encode_event(_event()))
    consumer, fake, router = _consumer(monkeypatch, [message])

    def fail(_message: Any) -> None:
        raise RetryableMessageError("temporary failure")

    metrics = consumer.run(fail, max_messages=1)
    consumer.close()

    assert metrics.to_dict() == {
        "consumed": 1,
        "processed": 0,
        "duplicates": 0,
        "failed": 1,
        "retried": 1,
        "dead_lettered": 0,
        "routing_failures": 0,
    }
    assert router.produced[0]["topic"] == "retry"
    headers = dict(router.produced[0]["headers"])
    assert headers[RETRY_COUNT_HEADER] == b"1"
    assert headers[ORIGIN_TOPIC_HEADER] == b"raw"
    assert fake.commits == [message]


def test_permanent_failure_routes_directly_to_dead_letter(monkeypatch: pytest.MonkeyPatch) -> None:
    message = FakeMessage(encode_event(_event()))
    consumer, fake, router = _consumer(monkeypatch, [message])

    def fail(_message: Any) -> None:
        raise PermanentMessageError("invalid business state")

    metrics = consumer.run(fail, max_messages=1)
    consumer.close()

    assert metrics.dead_lettered == 1
    assert metrics.retried == 0
    assert router.produced[0]["topic"] == "dlq"
    assert dict(router.produced[0]["headers"])[ERROR_CODE_HEADER] == b"PermanentMessageError"
    assert fake.commits == [message]


def test_exhausted_retry_routes_to_dead_letter_without_incrementing_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = FakeMessage(
        encode_event(_event()),
        topic="retry",
        headers={RETRY_COUNT_HEADER: b"3"},
    )
    consumer, _fake, router = _consumer(monkeypatch, [message], max_retries=3)

    def fail(_message: Any) -> None:
        raise RetryableMessageError("still unavailable")

    metrics = consumer.run(fail, max_messages=1)
    consumer.close()

    assert metrics.dead_lettered == 1
    assert router.produced[0]["topic"] == "dlq"
    assert dict(router.produced[0]["headers"])[RETRY_COUNT_HEADER] == b"3"


def test_duplicate_result_commits_without_routing(monkeypatch: pytest.MonkeyPatch) -> None:
    message = FakeMessage(encode_event(_event()))
    consumer, fake, router = _consumer(monkeypatch, [message])

    metrics = consumer.run(lambda _message: HandlingResult("duplicate"), max_messages=1)
    consumer.close()

    assert metrics.duplicates == 1
    assert metrics.processed == 0
    assert router.produced == []
    assert fake.commits == [message]


def test_failed_retry_delivery_seeks_and_does_not_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    message = FakeMessage(encode_event(_event()))
    router = FakeRoutingProducer(fail=True)
    consumer, fake, _router = _consumer(monkeypatch, [message], routing_producer=router)

    def fail(_message: Any) -> None:
        raise RetryableMessageError("temporary failure")

    with pytest.raises(KafkaDeliveryError, match="routing timed out|callback"):
        consumer.run(fail, max_messages=1)
    router.fail = False
    consumer.close()

    assert fake.commits == []
    assert fake.seeks[0].offset == message.offset()
    assert consumer.metrics.routing_failures == 1


def test_malformed_event_goes_directly_to_dead_letter(monkeypatch: pytest.MonkeyPatch) -> None:
    message = FakeMessage(b"not-json")
    consumer, fake, router = _consumer(monkeypatch, [message])

    metrics = consumer.run(lambda _message: None, max_messages=1)
    consumer.close()

    assert metrics.dead_lettered == 1
    assert router.produced[0]["topic"] == "dlq"
    assert dict(router.produced[0]["headers"])[ERROR_CODE_HEADER] == b"MessageSerializationError"
    assert fake.commits == [message]
