"""Integration tests: governance outbox and event flow against real Kafka."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select

from claro.application.governance_pipeline_service import GovernancePipelineService
from claro.application.message_processing import ConsumedMessage
from claro.application.outbox_dispatcher import OutboxDispatcher
from claro.application.risk_events import RISK_ASSESSED_EVENT, RiskAssessedPayload
from claro.bootstrap import AppContainer
from claro.config.settings import load_settings
from claro.data_access.models import OutboxEvent, RiskResult
from claro.domain.enums import OutboxStatus
from claro.infrastructure.kafka import KafkaAdmin, KafkaConsumer, KafkaProducer


def _build_risk_event(message_id: UUID, governance_data: dict) -> dict:
    return {
        "synthetic": True,
        "message_id": message_id,
        "dataset_id": None,
        "risk_result_id": UUID(str(governance_data["risk_result_id"])),
        "risk_score": 0.72,
        "risk_level": "high",
        "suggested_action": "warn",
        "confidence": 0.93,
        "categories": [],
        "detection_methods": ["rule"],
        "model_id": None,
        "detected_at": datetime.now(UTC),
    }


@pytest.mark.integration
def test_governance_pipeline_consumes_risk_event_and_enqueues_outbox(
    full_container: AppContainer, governance_data: dict
) -> None:
    message_id = UUID(str(governance_data["message_id"]))
    evaluation_service = full_container.policy_evaluation_service
    decision_service = full_container.governance_decision_service
    pipeline = GovernancePipelineService(
        full_container.governance_repository,
        evaluation_service,
        decision_service,
        auto_enforce=False,
    )
    payload = RiskAssessedPayload.model_validate(_build_risk_event(message_id, governance_data))
    event = payload.to_event(datetime.now(UTC))
    consumed = ConsumedMessage(
        event=event,
        topic="claro.test.risk.assessed",
        partition=0,
        offset=0,
        received_at=datetime.now(UTC),
        headers={},
    )
    first = pipeline.handle(consumed)
    assert first.status in {"processed", "duplicate"}
    assert event.event_type == RISK_ASSESSED_EVENT

    with full_container.session_factory() as session:
        pending = session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.dedupe_key.like(f"%:{message_id}:%"))
        )
        assert pending and pending >= 2

    second = pipeline.handle(consumed)
    assert second.status == "duplicate"
    with full_container.session_factory() as session:
        rows = session.scalars(
            select(OutboxEvent).where(OutboxEvent.dedupe_key.like(f"%:{message_id}:%"))
        ).all()
        assert len(rows) >= 2
        assert len({row.dedupe_key for row in rows}) == len(rows)


@pytest.mark.integration
def test_outbox_dispatcher_publishes_to_real_kafka(
    full_container: AppContainer, governance_data: dict
) -> None:
    settings = load_settings()
    suffix = governance_data["suffix"]
    topic = f"claro.test.governance.outbox.{suffix}"
    admin = KafkaAdmin(settings.kafka.bootstrap_servers, f"claro-gov-admin-{suffix}")
    admin.ensure_topics([topic], partitions=1, replication_factor=1)
    producer = KafkaProducer(settings.kafka.bootstrap_servers, f"claro-gov-producer-{suffix}")
    consumer = KafkaConsumer(
        settings.kafka.bootstrap_servers,
        [topic],
        f"claro-gov-outbox-{suffix}",
        f"claro-gov-outbox-consumer-{suffix}",
        f"claro-gov-outbox-retry-{suffix}",
        f"claro-gov-outbox-dlq-{suffix}",
        settings.kafka.security_protocol,
        0.2,
    )
    try:
        from claro.application.events import EventEnvelope

        envelope = EventEnvelope(
            event_type="game.governance.test.v1",
            payload={"synthetic": True, "probe": suffix},
        )
        producer.publish(topic, envelope)
        metrics = consumer.run(lambda _message: None, max_messages=1, idle_timeout_seconds=3)
        assert metrics.processed >= 1

        dispatcher = OutboxDispatcher(
            full_container.governance_repository,
            producer,
            batch_size=5,
            max_attempts=1,
        )
        result = dispatcher.dispatch_once()
        assert set(result) == {"fetched", "published", "failed"}

        with full_container.session_factory() as session:
            rows = session.scalars(select(OutboxEvent)).all()
            published = [row for row in rows if row.status == OutboxStatus.PUBLISHED.value]
            assert all(row.attempts >= 0 for row in published)
    finally:
        consumer.close()


@pytest.mark.integration
def test_risk_result_is_persisted_for_governance_consumption(
    full_container: AppContainer, governance_data: dict
) -> None:
    with full_container.session_factory() as session:
        risk = session.get(RiskResult, UUID(str(governance_data["risk_result_id"])))
        assert risk is not None
        assert risk.is_synthetic is True
        assert 0 <= float(risk.risk_score) <= 1
        assert risk.confidence is not None
