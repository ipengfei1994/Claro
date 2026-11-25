from __future__ import annotations

from unittest.mock import Mock

import pytest

from claro.application.events import EventEnvelope
from claro.infrastructure.kafka import KafkaEventBus
from claro.infrastructure.memory import InMemoryEventBus


def test_event_envelope_requires_event_type() -> None:
    with pytest.raises(ValueError, match="event_type"):
        EventEnvelope(event_type=" ", payload={})


def test_in_memory_bus_is_explicitly_simulated() -> None:
    bus = InMemoryEventBus()
    event = EventEnvelope(event_type="synthetic.test", payload={"value": 1})
    bus.publish(event)
    assert bus.transport == "in-memory-simulation"
    assert bus.snapshot() == [event]
    bus.close()
    assert bus.snapshot() == []


def test_kafka_close_reports_pending_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    producer = Mock()
    producer.flush.return_value = 1
    monkeypatch.setattr("claro.infrastructure.kafka.Producer", lambda _config: producer)
    bus = KafkaEventBus("localhost:9092", "claro.test.v1", "claro-test")

    with pytest.raises(TimeoutError, match="pending"):
        bus.close()

    producer.flush.assert_called_once_with(5)
