from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from claro.application.events import EventEnvelope
from claro.application.message_events import (
    MessageSerializationError,
    parse_persisted_game_message,
)
from claro.application.message_processing import (
    ConsumedMessage,
    HandlingResult,
    PermanentMessageError,
)
from claro.application.risk_events import RiskAssessedPayload
from claro.application.risk_service import RiskService, RiskServiceError


class EventPublisher(Protocol):
    def publish(
        self,
        topic: str,
        event: EventEnvelope,
        headers: Mapping[str, str] | None = None,
    ) -> Any: ...


class RiskPipelineService:
    """Consumes persisted messages, runs detection, publishes risk assessments.

    The risk assessment is published only after its result has been committed to
    PostgreSQL. The event id is the stable risk result id, so retries publish the
    same logical event and downstream consumers can deduplicate.
    """

    def __init__(
        self,
        service: RiskService,
        publisher: EventPublisher,
        risk_topic: str,
    ) -> None:
        self._service = service
        self._publisher = publisher
        self._risk_topic = risk_topic

    def handle(self, message: ConsumedMessage) -> HandlingResult:
        try:
            payload = parse_persisted_game_message(message.event)
        except MessageSerializationError as error:
            raise PermanentMessageError(str(error)) from error
        try:
            record = self._service.detect(payload.message_id)
        except RiskServiceError as error:
            raise PermanentMessageError(str(error)) from error
        event = (
            RiskAssessedPayload.from_stored(record.stored, synthetic=payload.synthetic)
            .with_dataset(payload.dataset_id)
            .to_event(trace_id=payload.trace_id)
        )
        self._publisher.publish(self._risk_topic, event)
        return HandlingResult("processed" if record.created else "duplicate")
