from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from claro.application.message_events import PersistedGameMessagePayload
from claro.application.message_processing import HandlingResult
from claro.application.risk_pipeline import RiskPipelineService
from claro.application.risk_service import RiskService
from claro.bootstrap import AppContainer
from claro.config.settings import load_settings
from claro.data_access.database import session_scope
from claro.data_access.models import Dataset, Message, RiskResult
from claro.data_access.repositories.risk_repository import RiskRepository
from claro.data_access.repositories.synthetic_repository import delete_synthetic_dataset
from claro.domain.enums import MessageStatus
from claro.infrastructure.kafka import (
    KafkaAdmin,
    KafkaConsumer,
    KafkaProducer,
)


@pytest.mark.integration
def test_processed_message_produces_risk_event(full_container: AppContainer) -> None:
    settings = load_settings()
    kafka = settings.kafka
    suffix = uuid4().hex[:12]
    dataset_name = f"phase-02-synthetic-risk-kafka-{suffix}"
    content = "免费代充 先付款后发货 https://scam-reward.invalid/x"
    with session_scope(full_container.session_factory) as session:
        dataset = Dataset(
            name=dataset_name,
            seed=20261125,
            generation_params={"synthetic": True, "template_version": 2},
            is_synthetic=True,
        )
        session.add(dataset)
        session.flush()
        message = Message(
            dataset_id=dataset.id,
            external_message_id=f"risk-kafka-{suffix}",
            sender_ref="synthetic-risk-player",
            server_ref="s1",
            channel="world",
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            language="zh-CN",
            status=MessageStatus.RECEIVED.value,
            occurred_at=datetime.now(UTC),
            is_synthetic=True,
        )
        session.add(message)
        session.flush()
        message_id = message.id
        dataset_id = dataset.id

    topics = {
        "processed": f"claro.test.risk.processed.{suffix}",
        "risk": f"claro.test.risk.assessed.{suffix}",
        "retry": f"claro.test.risk.retry.{suffix}",
        "dlq": f"claro.test.risk.dlq.{suffix}",
    }
    admin = KafkaAdmin(kafka.bootstrap_servers, f"claro-risk-it-admin-{suffix}")
    admin.ensure_topics(list(topics.values()), partitions=1, replication_factor=1)
    producer = KafkaProducer(kafka.bootstrap_servers, f"claro-risk-it-producer-{suffix}")
    repository = RiskRepository(full_container.session_factory)
    service = RiskService(settings, repository)
    pipeline = RiskPipelineService(service, producer, topics["risk"])
    group_id = f"claro-risk-it-{suffix}"

    def consumer(topic: str, group: str) -> KafkaConsumer:
        return KafkaConsumer(
            kafka.bootstrap_servers,
            [topic],
            group,
            f"claro-risk-it-consumer-{suffix}",
            topics["retry"],
            topics["dlq"],
            kafka.security_protocol,
            kafka.max_retries,
            0.2,
        )

    try:
        now = datetime.now(UTC)
        persisted = PersistedGameMessagePayload(
            synthetic=True,
            dataset_id=dataset_id,
            message_id=message_id,
            external_message_id=f"risk-kafka-{suffix}",
            trace_id=f"trace-{suffix}",
            status="received",
            source_topic="game.messages.raw",
            source_partition=0,
            source_offset=1,
            sent_at=now,
            received_at=now,
            persisted_at=now,
        ).to_event(now)
        producer.publish(topics["processed"], persisted)

        processed_consumer = consumer(topics["processed"], group_id)
        try:
            metrics = processed_consumer.run(pipeline.handle, max_messages=1)
        finally:
            processed_consumer.close()
        assert metrics.processed == 1
        assert metrics.failed == 0

        with full_container.session_factory() as session:
            stored = session.scalar(select(RiskResult).where(RiskResult.message_id == message_id))
            assert stored is not None
            risk_result_id = stored.id
            assert stored.is_synthetic is True

        assessments = []

        def capture(message) -> HandlingResult:
            assessments.append(message.event)
            return HandlingResult()

        risk_consumer = consumer(topics["risk"], f"claro-risk-it-risk-{suffix}")
        try:
            risk_metrics = risk_consumer.run(capture, max_messages=1)
        finally:
            risk_consumer.close()
        assert risk_metrics.processed == 1
        assert len(assessments) == 1
        event = assessments[0]
        assert event.event_type == "game.risk.assessed.v1"
        assert str(event.event_id) == str(risk_result_id)
        assert event.payload["risk_result_id"] == str(risk_result_id)
        assert event.payload["message_id"] == str(message_id)
        assert event.payload["dataset_id"] == str(dataset_id)
        assert event.payload["synthetic"] is True
        assert event.payload["suggested_action"] in {"block", "restrict"}

        duplicate = service.detect(message_id)
        assert duplicate.created is False
        assert duplicate.stored.risk_result_id == risk_result_id
    finally:
        producer.close()
        delete_synthetic_dataset(full_container.session_factory, dataset_name)
