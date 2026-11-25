from __future__ import annotations

from collections import deque
from threading import Lock

from claro.application.events import EventEnvelope
from claro.application.ports import EventBusPort


class InMemoryEventBus(EventBusPort):
    transport = "in-memory-simulation"

    def __init__(self, max_events: int = 1000) -> None:
        self._events: deque[EventEnvelope] = deque(maxlen=max_events)
        self._lock = Lock()

    def publish(self, event: EventEnvelope) -> None:
        with self._lock:
            self._events.append(event)

    def check(self) -> None:
        return None

    def close(self) -> None:
        with self._lock:
            self._events.clear()

    def snapshot(self) -> list[EventEnvelope]:
        with self._lock:
            return list(self._events)
