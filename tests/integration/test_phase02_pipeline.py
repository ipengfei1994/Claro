from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from claro.application.kafka_ingestion import KafkaIngestionService
from claro.application.message_events import (
    PERSISTED_GAME_MESSAGE_EVENT,
    RawGameMessagePayload,
)
from claro.application.message_processing import HandlingResult
from claro.bootstrap import AppContainer
from claro.config.settings import load_settings
from claro.data_access.database import create_database_engine, create_session_factory
from claro.data_access.models import InboxEvent, Message, MessageLabel, ProcessingEvent
from claro.data_access.repositories.synthetic_repository import delete_synthetic_dataset
from claro.data_generation.generator import GenerationSpec, generate_synthetic_dataset
from claro.infrastructure.kafka import (
    KafkaAdmin,
    KafkaConsumer,
    KafkaProducer,
)


@pytest.mark.integration
def test_generator_kafka_postgresql_pipeline_and_duplicate_delivery(
    full_container: AppContainer,
) -> None:
    settings = load_settings()
    kafka = settings.kafka
    suffix = uuid4().hex[:12]
    dataset_name = f"phase-02-synthetic-kafka-e2e-{suffix}"
    generated = generate_synthetic_dataset(
        GenerationSpec(
            players=20,
            servers=2,
            alliances=4,
            messages=100,
            policy_rules=8,
            name=dataset_name,
        )
    )
    topics = {
        "raw": f"claro.test.pipeline.raw.{suffix}",
        "processed": f"claro.test.pipeline.processed.{suffix}",
        "retry": f"claro.test.pipeline.retry.{suffix}",
        "dlq": f"claro.test.pipeline.dlq.{suffix}",
    }
    admin = KafkaAdmin(kafka.bootstrap_servers, "claro-pipeline-integration-admin")
    admin.ensure_topics(list(topics.values()), partitions=3, replication_factor=1)
    producer = KafkaProducer(kafka.bootstrap_servers, f"claro-pipeline-producer-{suffix}")
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    service = KafkaIngestionService(session_factory, producer, topics["processed"])
    group_id = f"claro-pipeline-{suffix}"

    def consumer(topic: str, group: str) -> KafkaConsumer:
        return KafkaConsumer(
            kafka.bootstrap_servers,
            [topic],
            group,
            f"claro-pipeline-consumer-{suffix}",
            topics["retry"],
            topics["dlq"],
            kafka.security_protocol,
            kafka.max_retries,
            0.2,
        )

    try:
        events = [
            (
                topics["raw"],
                RawGameMessagePayload.from_json_mapping(message.raw_payload()).to_event(),
                None,
            )
            for message in generated.messages
        ]
        for start in range(0, len(events), 25):
            producer.publish_many(events[start : start + 25])

        raw_consumer = consumer(topics["raw"], group_id)
        try:
            metrics = raw_consumer.run(service.handle, max_messages=100, idle_timeout_seconds=2)
        finally:
            raw_consumer.close()
        assert metrics.processed == 100
        assert metrics.failed == 0

        with Session(engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(Message)
                    .where(Message.dataset_id == generated.dataset.id)
                )
                == 100
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(InboxEvent)
                    .where(
                        InboxEvent.event_id.in_(
                            select(Message.id).where(Message.dataset_id == generated.dataset.id)
                        )
                    )
                )
                == 100
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ProcessingEvent)
                    .where(
                        ProcessingEvent.message_id.in_(
                            select(Message.id).where(Message.dataset_id == generated.dataset.id)
                        )
                    )
                )
                == 100
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(MessageLabel)
                    .where(MessageLabel.dataset_id == generated.dataset.id)
                )
                == 0
            )

        producer.publish_many(events[:10])
        raw_consumer = consumer(topics["raw"], group_id)
        try:
            duplicate_metrics = raw_consumer.run(
                service.handle, max_messages=10, idle_timeout_seconds=2
            )
        finally:
            raw_consumer.close()
        assert duplicate_metrics.duplicates == 10
        assert duplicate_metrics.processed == 0

        with Session(engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(Message)
                    .where(Message.dataset_id == generated.dataset.id)
                )
                == 100
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ProcessingEvent)
                    .where(
                        ProcessingEvent.message_id.in_(
                            select(Message.id).where(Message.dataset_id == generated.dataset.id)
                        )
                    )
                )
                == 100
            )

        processed_events = []

        def capture_processed(message) -> HandlingResult:
            processed_events.append(message.event)
            return HandlingResult()

        processed_consumer = consumer(topics["processed"], f"claro-processed-{suffix}")
        try:
            processed_metrics = processed_consumer.run(
                capture_processed, max_messages=110, idle_timeout_seconds=2
            )
        finally:
            processed_consumer.close()
        assert processed_metrics.processed == 110
        assert all(event.event_type == PERSISTED_GAME_MESSAGE_EVENT for event in processed_events)
        assert all("content" not in event.payload for event in processed_events)
        assert all("label" not in event.payload for event in processed_events)
        assert len({event.event_id for event in processed_events}) == 100

        status = admin.consumer_group_status(group_id)
        assert status.total_lag == 0
    finally:
        producer.close()
        try:
            delete_synthetic_dataset(session_factory, dataset_name)
        except ValueError as error:
            if "dataset not found" not in str(error):
                raise
        engine.dispose()
