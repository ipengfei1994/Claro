from __future__ import annotations

from unittest.mock import Mock

import pytest

from claro.bootstrap import AppContainer, create_app_container
from claro.config.settings import ClaroSettings
from claro.infrastructure.memory import InMemoryEventBus


def test_development_container_starts_without_external_services() -> None:
    settings = ClaroSettings(
        _env_file=None,
        app={"mode": "development"},
        database={"url": "sqlite:///:memory:"},
        redis={"enabled": False},
        kafka={"enabled": False},
    )
    container = create_app_container(settings)
    try:
        container.verify_connections()
        assert isinstance(container.event_bus, InMemoryEventBus)
        assert container.cache is None
        statuses = {result.name: result.status for result in container.health_service.check_all()}
        assert statuses == {"sqlite": "healthy", "redis": "disabled", "kafka": "disabled"}
        event = container.publish_test_event()
        assert container.event_bus.transport == "in-memory-simulation"
        assert event.payload["synthetic"] is True
    finally:
        container.close()


def test_close_attempts_all_resources_when_event_bus_fails() -> None:
    event_bus = Mock()
    event_bus.close.side_effect = RuntimeError("bus close failed")
    cache = Mock()
    engine = Mock()
    container = AppContainer(
        settings=ClaroSettings(_env_file=None),
        engine=engine,
        session_factory=Mock(),
        event_bus=event_bus,
        cache=cache,
        safety_cache=None,
        health_service=Mock(),
    )

    with pytest.raises(ExceptionGroup, match="failed to close application resources"):
        container.close()

    cache.close.assert_called_once_with()
    engine.dispose.assert_called_once_with()
