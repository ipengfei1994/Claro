from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from confluent_kafka import KafkaException
from sqlalchemy.exc import SQLAlchemyError

from claro.config.settings import load_settings, redact_database_url
from claro.data_generation.generator import GenerationSpec


def _add_generation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--seed", type=int, default=20261125)
    parser.add_argument("--players", type=int, default=5_000)
    parser.add_argument("--servers", type=int, default=10)
    parser.add_argument("--alliances", type=int, default=500)
    parser.add_argument("--messages", type=int, default=50_000)
    parser.add_argument("--policy-rules", type=int, default=40)
    parser.add_argument("--days", type=int, default=31)
    parser.add_argument("--name")


def _generation_spec(args: argparse.Namespace) -> GenerationSpec:
    return GenerationSpec(
        seed=args.seed,
        players=args.players,
        servers=args.servers,
        alliances=args.alliances,
        messages=args.messages,
        policy_rules=args.policy_rules,
        days=args.days,
        name=args.name,
    )


def _json_default(value: object) -> str:
    """Render the non-JSON types that appear in status payloads."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _print_json(payload: object, output: Path | None = None) -> None:
    # UUID and datetime values appear in status payloads; rendering them as ISO
    # text keeps every command printable instead of failing on the first
    # non-JSON type.
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
    print(rendered)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claro", description="Claro content governance platform")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check-config", help="validate merged configuration")
    subparsers.add_parser("check-db", help="verify database connectivity")
    subparsers.add_parser("check-services", help="verify all enabled service connections")
    subparsers.add_parser("info", help="show non-sensitive runtime information")
    subparsers.add_parser("seed", help="create deterministic synthetic verification data")

    generate_parser = subparsers.add_parser(
        "generate-data", help="generate reproducible synthetic SLG data without writing a database"
    )
    _add_generation_arguments(generate_parser)
    generate_parser.add_argument("--output", type=Path)

    load_parser = subparsers.add_parser(
        "load-data", help="generate and bulk-load synthetic data into PostgreSQL"
    )
    _add_generation_arguments(load_parser)
    load_parser.add_argument("--batch-size", type=int, default=1_000)
    load_parser.add_argument("--clean", action="store_true")

    clean_parser = subparsers.add_parser(
        "clean-data", help="delete only the selected Phase 02 synthetic dataset"
    )
    clean_parser.add_argument("--dataset", required=True)

    quality_parser = subparsers.add_parser(
        "check-data", help="run relational and distribution checks for a synthetic dataset"
    )
    quality_parser.add_argument("--dataset", required=True)

    warehouse_parser = subparsers.add_parser(
        "warehouse-export", help="export PostgreSQL snapshots and Hive ODS load SQL"
    )
    warehouse_mode = warehouse_parser.add_mutually_exclusive_group()
    warehouse_mode.add_argument("--full", action="store_true")
    warehouse_mode.add_argument("--since")
    warehouse_parser.add_argument("--output", type=Path, required=True)
    warehouse_parser.add_argument("--dataset")
    warehouse_parser.add_argument(
        "--tables",
        nargs="+",
        choices=("message", "risk_event", "policy_decision", "moderation_record"),
        default=("message", "risk_event", "policy_decision", "moderation_record"),
    )

    subparsers.add_parser("kafka-topics", help="create and list all Phase 02 Kafka topics")
    kafka_produce_parser = subparsers.add_parser(
        "kafka-produce", help="independently publish synthetic raw messages to Kafka"
    )
    _add_generation_arguments(kafka_produce_parser)
    kafka_produce_parser.add_argument("--batch-size", type=int, default=1_000)
    kafka_produce_parser.add_argument("--start-index", type=int, default=0)
    kafka_produce_parser.add_argument("--topic")
    kafka_consume_parser = subparsers.add_parser(
        "kafka-consume",
        help="independently consume Kafka events, optionally persisting them to PostgreSQL",
    )
    kafka_consume_parser.add_argument("--topic")
    kafka_consume_parser.add_argument("--group")
    kafka_consume_parser.add_argument("--max-messages", type=int)
    kafka_consume_parser.add_argument("--idle-timeout", type=float, default=5.0)
    kafka_consume_parser.add_argument(
        "--offset-reset", choices=("earliest", "latest"), default="earliest"
    )
    kafka_consume_parser.add_argument("--persist", action="store_true")
    kafka_consume_parser.add_argument("--continuous", action="store_true")
    kafka_group_parser = subparsers.add_parser(
        "kafka-group", help="inspect Consumer Group state, committed offsets and lag"
    )
    kafka_group_parser.add_argument("--group")

    subparsers.add_parser("risk-status", help="show risk engine configuration and active model")
    risk_sync_parser = subparsers.add_parser(
        "risk-sync-rules", help="synchronize YAML detection rules into PostgreSQL"
    )
    risk_sync_parser.add_argument("--output", type=Path)

    risk_train_parser = subparsers.add_parser(
        "risk-train", help="train the multi-label risk model on a synthetic dataset"
    )
    risk_train_parser.add_argument("--dataset", required=True)
    risk_train_parser.add_argument("--algorithm", choices=("logistic_regression", "linear_svm"))
    risk_train_parser.add_argument("--output", type=Path)

    risk_evaluate_parser = subparsers.add_parser(
        "risk-evaluate", help="evaluate a model and persist metrics and error cases"
    )
    risk_evaluate_parser.add_argument("--dataset", required=True)
    risk_evaluate_parser.add_argument(
        "--split", choices=("train", "validation", "test"), default="test"
    )
    risk_evaluate_parser.add_argument("--model")
    risk_evaluate_parser.add_argument("--no-persist", action="store_true")
    risk_evaluate_parser.add_argument("--output", type=Path)

    risk_detect_parser = subparsers.add_parser(
        "risk-detect", help="run detection for one message, pending dataset messages, or text"
    )
    risk_target = risk_detect_parser.add_mutually_exclusive_group(required=True)
    risk_target.add_argument("--message")
    risk_target.add_argument("--dataset")
    risk_target.add_argument("--text")
    risk_detect_parser.add_argument("--limit", type=int, default=100)
    risk_detect_parser.add_argument("--force", action="store_true")
    risk_detect_parser.add_argument("--output", type=Path)

    risk_result_parser = subparsers.add_parser(
        "risk-result", help="show the stored risk result and findings for a message"
    )
    risk_result_parser.add_argument("--message", required=True)
    risk_result_parser.add_argument("--output", type=Path)

    risk_pipeline_parser = subparsers.add_parser(
        "risk-pipeline",
        help="consume persisted messages, detect risk, and publish risk assessments",
    )
    risk_pipeline_parser.add_argument("--group")
    risk_pipeline_parser.add_argument("--max-messages", type=int)
    risk_pipeline_parser.add_argument("--idle-timeout", type=float, default=5.0)
    risk_pipeline_parser.add_argument(
        "--offset-reset", choices=("earliest", "latest"), default="earliest"
    )

    risk_cases_parser = subparsers.add_parser(
        "risk-cases", help="list stored evaluation error cases for an evaluation run"
    )
    risk_cases_parser.add_argument("--run", required=True)
    risk_cases_parser.add_argument(
        "--type",
        choices=("false_positive", "false_negative", "conflicting", "low_confidence", "borderline"),
    )
    risk_cases_parser.add_argument("--limit", type=int, default=200)
    risk_cases_parser.add_argument("--output", type=Path)

    subparsers.add_parser(
        "governance-seed-policies", help="create the default and catalog governance policies"
    )
    governance_evaluate = subparsers.add_parser(
        "governance-evaluate", help="evaluate active policies for one message"
    )
    governance_evaluate.add_argument("--message", required=True)
    governance_evaluate.add_argument("--output", type=Path)
    governance_decide = subparsers.add_parser(
        "governance-decide", help="produce a governance decision from a message evaluation"
    )
    governance_decide.add_argument("--message", required=True)
    governance_decide.add_argument("--output", type=Path)
    governance_status = subparsers.add_parser(
        "governance-status", help="show governance dashboard counters and outbox state"
    )
    governance_status.add_argument("--output", type=Path)
    governance_pipeline = subparsers.add_parser(
        "governance-pipeline",
        help="consume risk assessments and run evaluation, decision and enforcement",
    )
    governance_pipeline.add_argument("--group")
    governance_pipeline.add_argument("--max-messages", type=int)
    governance_pipeline.add_argument("--idle-timeout", type=float, default=5.0)
    governance_pipeline.add_argument(
        "--offset-reset", choices=("earliest", "latest"), default="earliest"
    )
    governance_pipeline.add_argument("--no-auto-enforce", action="store_true")
    governance_pipeline.add_argument("--dispatch-outbox", action="store_true")
    governance_outbox = subparsers.add_parser(
        "governance-dispatch-outbox", help="publish pending governance outbox events to Kafka"
    )
    governance_outbox.add_argument("--max-batches", type=int, default=100)
    governance_outbox.add_argument("--output", type=Path)
    governance_expire = subparsers.add_parser(
        "governance-expire-enforcements", help="expire due simulated enforcement actions"
    )
    governance_expire.add_argument("--limit", type=int, default=500)
    governance_expire.add_argument("--output", type=Path)

    process_message_parser = subparsers.add_parser(
        "process-message",
        help="run one message through ingestion, detection, policy and decision",
    )
    process_message_parser.add_argument("--text", help="message content to process")
    process_message_parser.add_argument("--message", help="existing message UUID to re-process")
    process_message_parser.add_argument("--player", default="demo-player-cli")
    process_message_parser.add_argument("--server", default="server-1")
    process_message_parser.add_argument("--channel", default="world")
    process_message_parser.add_argument("--dataset", default="phase-06-cli")
    process_message_parser.add_argument("--no-publish", action="store_true")
    process_message_parser.add_argument("--output", type=Path)

    demo_run_parser = subparsers.add_parser(
        "demo-run", help="execute the deterministic 14-step demonstration"
    )
    demo_run_parser.add_argument("--output", type=Path)
    subparsers.add_parser("demo-status", help="show whether the demo dataset exists")
    demo_clean_parser = subparsers.add_parser(
        "demo-clean", help="delete only the demonstration dataset"
    )
    demo_clean_parser.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt"
    )
    demo_clean_parser.add_argument("--output", type=Path)

    for name, help_text in (
        ("analytics-overview", "show Phase 05 overview KPIs"),
        ("analytics-risk", "show risk trend, categories and severity"),
        ("analytics-community", "show server, alliance and player analytics"),
        ("analytics-governance", "show governance, moderation and enforcement analytics"),
        ("analytics-model", "show persisted model performance"),
        ("analytics-strategy", "show historical policy performance"),
        ("analytics-quality", "run analytical data-quality checks"),
    ):
        parser_item = subparsers.add_parser(name, help=help_text)
        parser_item.add_argument("--days", type=int, default=365)
        parser_item.add_argument("--dataset", help="dataset name; defaults to all datasets")
        parser_item.add_argument("--output", type=Path)
        if name == "analytics-risk":
            parser_item.add_argument(
                "--grain", choices=("hour", "day", "week", "month"), default="day"
            )
        if name == "analytics-community":
            parser_item.add_argument("--limit", type=int, default=100)

    report_parser = subparsers.add_parser(
        "analytics-report", help="generate an analytical report with CSV tables"
    )
    report_parser.add_argument(
        "--type",
        choices=(
            "daily_risk",
            "weekly_risk",
            "governance_performance",
            "policy_evaluation",
            "model_performance",
        ),
        default="daily_risk",
    )
    report_parser.add_argument("--days", type=int, default=1)
    report_parser.add_argument("--dataset", help="dataset name; defaults to all datasets")
    report_parser.add_argument("--output-dir", type=Path, default=Path("runtime/reports"))

    replay_parser = subparsers.add_parser(
        "strategy-replay", help="run an isolated strategy replay on historical messages"
    )
    replay_parser.add_argument("--days", type=int, default=365)
    replay_parser.add_argument("--dataset", help="dataset name; defaults to all datasets")
    replay_parser.add_argument("--sample-limit", type=int, default=500)
    replay_parser.add_argument(
        "--action-override",
        nargs="*",
        default=[],
        metavar="POLICY=ACTION",
        help="override a policy action in the candidate set",
    )
    replay_parser.add_argument(
        "--disabled", nargs="*", default=[], metavar="POLICY", help="disable policies in candidate"
    )
    replay_parser.add_argument("--candidate-label", default="candidate")
    replay_parser.add_argument("--output", type=Path)

    subparsers.add_parser("serve", help="start the Streamlit operations interface")
    return parser


def _print_info() -> None:
    settings = load_settings()
    database_url = settings.resolved_database_url()
    if database_url.startswith("postgresql+psycopg://"):
        database_url = redact_database_url(database_url)
    payload = {
        "product": "Claro",
        "version": "0.1.0",
        "mode": settings.app.mode,
        "database": database_url.split(":", 1)[0],
        "redis": "enabled" if settings.redis.enabled else "disabled",
        "kafka": "enabled" if settings.kafka.enabled else "disabled",
        "log_directory": str(settings.resolved_log_directory()),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _kafka_enabled_settings():
    settings = load_settings()
    if not settings.kafka.enabled or not settings.kafka.bootstrap_servers:
        raise ValueError("Kafka is disabled or CLARO_KAFKA__BOOTSTRAP_SERVERS is missing")
    return settings


def _run_kafka_topics() -> dict[str, Any]:
    from claro.infrastructure.kafka import KafkaAdmin, KafkaTopics

    settings = _kafka_enabled_settings()
    kafka = settings.kafka
    admin = KafkaAdmin(kafka.bootstrap_servers, kafka.client_id, kafka.security_protocol)
    topics = KafkaTopics(
        raw=kafka.raw_topic,
        processed=kafka.processed_topic,
        risk=kafka.risk_topic,
        moderation=kafka.moderation_topic,
        retry=kafka.retry_topic,
        dead_letter=kafka.dead_letter_topic,
    )
    admin.ensure_topics(
        topics.all(),
        partitions=kafka.partitions,
        replication_factor=kafka.replication_factor,
    )
    return {"topics": admin.list_topics()}


def _run_kafka_produce(args: argparse.Namespace) -> dict[str, Any]:
    from claro.application.message_events import RawGameMessagePayload
    from claro.data_generation.generator import generate_synthetic_dataset
    from claro.infrastructure.kafka import KafkaAdmin, KafkaProducer

    if args.batch_size < 1:
        raise ValueError("batch_size must be positive")
    if args.start_index < 0:
        raise ValueError("start_index must not be negative")
    settings = _kafka_enabled_settings()
    kafka = settings.kafka
    topic = args.topic or kafka.raw_topic
    generated = generate_synthetic_dataset(_generation_spec(args))
    if args.start_index > len(generated.messages):
        raise ValueError("start_index exceeds the generated message count")
    KafkaAdmin(
        kafka.bootstrap_servers,
        kafka.client_id,
        kafka.security_protocol,
    ).ensure_topics(
        [topic],
        partitions=kafka.partitions,
        replication_factor=kafka.replication_factor,
    )
    producer = KafkaProducer(
        kafka.bootstrap_servers,
        f"{kafka.client_id}-producer",
        kafka.security_protocol,
        kafka.producer_timeout_ms,
    )
    deliveries = []
    try:
        for start in range(args.start_index, len(generated.messages), args.batch_size):
            batch = generated.messages[start : start + args.batch_size]
            events = [
                (
                    topic,
                    RawGameMessagePayload.from_json_mapping(message.raw_payload()).to_event(),
                    None,
                )
                for message in batch
            ]
            deliveries.extend(producer.publish_many(events))
    finally:
        producer.close()
    return {
        "dataset": generated.dataset.name,
        "fingerprint": generated.fingerprint(),
        "topic": topic,
        "generated_messages": len(generated.messages),
        "start_index": args.start_index,
        "produced": len(deliveries),
        "batch_size": args.batch_size,
        "first_sent_at": deliveries[0].sent_at.isoformat() if deliveries else None,
        "last_sent_at": deliveries[-1].sent_at.isoformat() if deliveries else None,
        "offset_min": min((item.offset for item in deliveries), default=None),
        "offset_max": max((item.offset for item in deliveries), default=None),
        "partitions": sorted({item.partition for item in deliveries}),
    }


def _run_kafka_consume(args: argparse.Namespace) -> dict[str, Any]:
    from claro.application.message_events import RAW_GAME_MESSAGE_EVENT, parse_raw_game_message
    from claro.infrastructure.kafka import (
        HandlingResult,
        KafkaAdmin,
        KafkaConsumer,
        KafkaProducer,
    )

    settings = _kafka_enabled_settings()
    kafka = settings.kafka
    topic = args.topic or kafka.raw_topic
    group_id = args.group or (
        kafka.retry_consumer_group if topic == kafka.retry_topic else kafka.consumer_group
    )
    required_topics = [topic, kafka.retry_topic, kafka.dead_letter_topic]
    if args.persist:
        required_topics.append(kafka.processed_topic)
    KafkaAdmin(
        kafka.bootstrap_servers,
        kafka.client_id,
        kafka.security_protocol,
    ).ensure_topics(
        required_topics,
        partitions=kafka.partitions,
        replication_factor=kafka.replication_factor,
    )
    engine = None
    publisher = None
    if args.persist:
        from claro.application.kafka_ingestion import KafkaIngestionService
        from claro.data_access.database import create_database_engine, create_session_factory

        engine = create_database_engine(settings)
        publisher = KafkaProducer(
            kafka.bootstrap_servers,
            f"{kafka.client_id}-processed-publisher",
            kafka.security_protocol,
            kafka.producer_timeout_ms,
        )
        handle = KafkaIngestionService(
            create_session_factory(engine),
            publisher,
            kafka.processed_topic,
        ).handle
        client_id = f"{kafka.client_id}-pipeline-consumer"
    else:

        def handle(message) -> HandlingResult:
            if message.event.event_type == RAW_GAME_MESSAGE_EVENT:
                payload = parse_raw_game_message(message.event)
                event_payload = {
                    "message_id": str(payload.message_id),
                    "synthetic": payload.synthetic,
                    "content_hash": payload.content_hash,
                }
            else:
                event_payload = {"event_id": str(message.event.event_id)}
            print(
                json.dumps(
                    {
                        "event": event_payload,
                        "received_at": message.received_at.isoformat(),
                        "topic": message.topic,
                        "partition": message.partition,
                        "offset": message.offset,
                        "retry_count": message.retry_count,
                    },
                    ensure_ascii=False,
                )
            )
            return HandlingResult()

        client_id = f"{kafka.client_id}-diagnostic-consumer"

    consumer = KafkaConsumer(
        kafka.bootstrap_servers,
        [topic],
        group_id,
        client_id,
        kafka.retry_topic,
        kafka.dead_letter_topic,
        kafka.security_protocol,
        kafka.max_retries,
        kafka.poll_timeout_seconds,
        kafka.producer_timeout_ms,
        args.offset_reset,
    )
    try:
        metrics = consumer.run(
            handle,
            max_messages=args.max_messages,
            idle_timeout_seconds=None if args.continuous else args.idle_timeout,
        )
    finally:
        consumer.close()
        if publisher is not None:
            publisher.close()
        if engine is not None:
            engine.dispose()
    status = KafkaAdmin(
        kafka.bootstrap_servers,
        kafka.client_id,
        kafka.security_protocol,
    ).consumer_group_status(group_id)
    return {
        "mode": "postgresql-pipeline" if args.persist else "diagnostic",
        "topic": topic,
        "group": status.to_dict(),
        "metrics": metrics.to_dict(),
    }


def _run_kafka_group(args: argparse.Namespace) -> dict[str, Any]:
    from claro.infrastructure.kafka import KafkaAdmin

    settings = _kafka_enabled_settings()
    kafka = settings.kafka
    status = KafkaAdmin(
        kafka.bootstrap_servers,
        kafka.client_id,
        kafka.security_protocol,
    ).consumer_group_status(args.group or kafka.consumer_group)
    return status.to_dict()


@contextmanager
def _risk_service() -> Iterator[tuple[Any, Any]]:
    from claro.application.risk_service import RiskService
    from claro.data_access.database import create_database_engine, create_session_factory
    from claro.data_access.repositories.risk_repository import RiskRepository

    settings = load_settings()
    engine = create_database_engine(settings)
    cache = None
    try:
        if settings.redis.enabled and settings.redis.url:
            from claro.infrastructure.redis import RedisCacheAdapter

            cache = RedisCacheAdapter(settings.redis.url, settings.redis.socket_timeout)
        service = RiskService(
            settings,
            RiskRepository(create_session_factory(engine)),
            cache=cache,
        )
        yield settings, service
    finally:
        if cache is not None:
            cache.close()
        engine.dispose()


def _run_risk_detect(args: argparse.Namespace) -> dict[str, Any]:
    from uuid import UUID

    with _risk_service() as (_settings, service):
        if args.text is not None:
            result = service.analyze_text(args.text)
            return {**result.to_dict(), "persisted": False}
        if args.message is not None:
            record = service.detect(UUID(args.message), force=args.force)
            return {
                "created": record.created,
                "risk_result": record.stored.to_dict(),
                "findings": service.explain(UUID(args.message))["findings"],
            }
        if args.limit < 1:
            raise ValueError("limit must be positive")
        return service.detect_pending(args.dataset, limit=args.limit)


def _run_risk_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    from claro.application.risk_pipeline import RiskPipelineService
    from claro.application.risk_service import RiskService
    from claro.data_access.database import create_database_engine, create_session_factory
    from claro.data_access.repositories.risk_repository import RiskRepository
    from claro.infrastructure.kafka import (
        KafkaAdmin,
        KafkaConsumer,
        KafkaProducer,
    )

    settings = _kafka_enabled_settings()
    kafka = settings.kafka
    group_id = args.group or f"{kafka.consumer_group}.risk"
    KafkaAdmin(
        kafka.bootstrap_servers,
        kafka.client_id,
        kafka.security_protocol,
    ).ensure_topics(
        [kafka.processed_topic, kafka.risk_topic, kafka.retry_topic, kafka.dead_letter_topic],
        partitions=kafka.partitions,
        replication_factor=kafka.replication_factor,
    )
    engine = create_database_engine(settings)
    cache = None
    publisher = None
    consumer = None
    try:
        if settings.redis.enabled and settings.redis.url:
            from claro.infrastructure.redis import RedisCacheAdapter

            cache = RedisCacheAdapter(settings.redis.url, settings.redis.socket_timeout)
        service = RiskService(
            settings,
            RiskRepository(create_session_factory(engine)),
            cache=cache,
        )
        publisher = KafkaProducer(
            kafka.bootstrap_servers,
            f"{kafka.client_id}-risk-publisher",
            kafka.security_protocol,
            kafka.producer_timeout_ms,
        )
        handler = RiskPipelineService(service, publisher, kafka.risk_topic)
        consumer = KafkaConsumer(
            kafka.bootstrap_servers,
            [kafka.processed_topic],
            group_id,
            f"{kafka.client_id}-risk-consumer",
            kafka.retry_topic,
            kafka.dead_letter_topic,
            kafka.security_protocol,
            kafka.max_retries,
            kafka.poll_timeout_seconds,
            kafka.producer_timeout_ms,
            args.offset_reset,
        )
        metrics = consumer.run(
            handler.handle,
            max_messages=args.max_messages,
            idle_timeout_seconds=args.idle_timeout,
        )
        status = KafkaAdmin(
            kafka.bootstrap_servers,
            kafka.client_id,
            kafka.security_protocol,
        ).consumer_group_status(group_id)
        return {
            "topic": kafka.processed_topic,
            "risk_topic": kafka.risk_topic,
            "group": status.to_dict(),
            "metrics": metrics.to_dict(),
        }
    finally:
        if consumer is not None:
            consumer.close()
        if publisher is not None:
            publisher.close()
        if cache is not None:
            cache.close()
        engine.dispose()


@contextmanager
def _governance_container() -> Iterator[Any]:
    from claro.bootstrap import create_app_container

    container = create_app_container()
    try:
        yield container
    finally:
        container.close()


def _analytics_filters(args: argparse.Namespace) -> Any:
    from claro.analytics.reports import default_filters

    return default_filters(days=args.days, dataset_name=getattr(args, "dataset", None))


def _run_analytics_command(args: argparse.Namespace) -> dict[str, Any]:
    from claro.analytics.reports import REPORT_TYPES, ReportService

    with _governance_container() as container:
        service = container.analytics_service
        if service is None:
            raise RuntimeError("analytics service is not available")
        filters = _analytics_filters(args)
        command = args.command
        if command == "analytics-overview":
            return service.overview(filters)
        if command == "analytics-risk":
            return service.risk(filters, args.grain)
        if command == "analytics-community":
            return service.community(filters, limit=args.limit)
        if command == "analytics-governance":
            return service.governance(filters)
        if command == "analytics-model":
            return service.model(filters)
        if command == "analytics-strategy":
            return service.strategy(filters)
        if command == "analytics-quality":
            return service.quality()
        if command == "analytics-report":
            if args.type not in REPORT_TYPES:
                raise ValueError(f"unsupported report type: {args.type}")
            replay_service = container.strategy_replay_service
            report = ReportService(service, replay_service).generate(args.type, filters)
            files = ReportService(service, replay_service).export(report, args.output_dir)
            return {
                "report_type": args.type,
                "executive_summary": report["executive_summary"],
                "files": [str(path) for path in files],
            }
        if command == "strategy-replay":
            replay_service = container.strategy_replay_service
            if replay_service is None:
                raise RuntimeError("strategy replay service is not available")
            candidate = {
                "action_overrides": dict(
                    item.split("=", 1) for item in args.action_override if "=" in item
                ),
                "disabled_policies": list(args.disabled),
                "candidate_label": args.candidate_label,
            }
            return replay_service.run(
                filters, candidate, sample_limit=args.sample_limit, executed_by="cli"
            )
        raise ValueError(f"unsupported analytics command: {command}")


def _governance_message_uuid(raw: str) -> Any:
    from uuid import UUID

    try:
        return UUID(raw)
    except ValueError as error:
        raise ValueError(f"invalid message id: {raw}") from error


def _run_governance_evaluate(args: argparse.Namespace) -> dict[str, Any]:
    with _governance_container() as container:
        service = container.policy_evaluation_service
        result = service.evaluate_message(_governance_message_uuid(args.message))
        return {
            "evaluation_id": result.get("id"),
            "selected_policy_id": result.get("selected_policy_id"),
            "suggested_action": result.get("suggested_action"),
            "evaluation_reason": result.get("evaluation_reason"),
            "matched": result.get("matched", []),
            "conflicts": result.get("conflicts", []),
            "selected_is_default": result.get("selected_is_default"),
        }


def _run_governance_decide(args: argparse.Namespace) -> dict[str, Any]:
    with _governance_container() as container:
        message_id = _governance_message_uuid(args.message)
        evaluation = container.policy_evaluation_service.evaluate_message(message_id)
        decision = container.governance_decision_service.make_decision(evaluation)
        return {
            "decision_id": decision.get("id"),
            "action": decision.get("action"),
            "decision_status": decision.get("decision_status"),
            "requires_review": decision.get("requires_review"),
            "priority": decision.get("priority"),
            "decision_reason": decision.get("decision_reason"),
            "case_id": decision.get("case_id"),
            "auto_executable": decision.get("auto_executable"),
            "downgraded": decision.get("downgraded"),
        }


def _run_governance_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    from claro.application.enforcement_service import EnforcementService
    from claro.application.governance_cache import GovernanceCacheService
    from claro.application.governance_decision_service import GovernanceDecisionService
    from claro.application.governance_pipeline_service import GovernancePipelineService
    from claro.application.outbox_dispatcher import OutboxDispatcher
    from claro.application.policy_evaluation_service import PolicyEvaluationService
    from claro.application.policy_service import PolicyService
    from claro.data_access.database import create_database_engine, create_session_factory
    from claro.data_access.repositories.governance_repository import (
        GovernanceRepository,
        GovernanceTopics,
    )
    from claro.data_access.repositories.policy_repository import PolicyRepository
    from claro.governance.decision import DecisionThresholds
    from claro.infrastructure.kafka import KafkaAdmin, KafkaConsumer, KafkaProducer

    settings = _kafka_enabled_settings()
    kafka = settings.kafka
    governance = settings.governance
    group_id = args.group or f"{governance.consumer_group}.pipeline"
    governance_topics = list(governance.topics.all())
    KafkaAdmin(
        kafka.bootstrap_servers,
        kafka.client_id,
        kafka.security_protocol,
    ).ensure_topics(
        [kafka.risk_topic, *governance_topics, kafka.retry_topic, kafka.dead_letter_topic],
        partitions=kafka.partitions,
        replication_factor=kafka.replication_factor,
    )
    engine = create_database_engine(settings)
    cache = None
    publisher = None
    consumer = None
    outbox_result: dict[str, Any] | None = None
    try:
        if settings.redis.enabled and settings.redis.url:
            from claro.infrastructure.redis import RedisCacheAdapter

            cache = RedisCacheAdapter(settings.redis.url, settings.redis.socket_timeout)
        session_factory = create_session_factory(engine)
        repository = GovernanceRepository(
            session_factory,
            topics=GovernanceTopics(
                evaluated=governance.topics.evaluated,
                decision=governance.topics.decisions,
                moderation=governance.topics.moderation,
                enforcement=governance.topics.enforcement,
                feedback=governance.topics.feedback,
            ),
        )
        policy_service = PolicyService(
            PolicyRepository(session_factory),
            cache=cache,
            cache_ttl_seconds=governance.policy_cache_ttl_seconds,
        )
        governance_cache = (
            GovernanceCacheService(
                cache, repository, rate_window_seconds=governance.rate_limit_window_seconds
            )
            if cache is not None
            else None
        )
        publisher = KafkaProducer(
            kafka.bootstrap_servers,
            f"{kafka.client_id}-governance-publisher",
            kafka.security_protocol,
            kafka.producer_timeout_ms,
        )
        handler = GovernancePipelineService(
            repository,
            PolicyEvaluationService(
                repository,
                policy_service,
                cache=governance_cache,
                rate_window_seconds=governance.rate_limit_window_seconds,
            ),
            GovernanceDecisionService(
                repository,
                thresholds=DecisionThresholds(
                    low_confidence=governance.low_confidence_threshold,
                    high_risk_confidence=governance.high_risk_confidence_threshold,
                ),
                review_sla_hours=governance.review_sla_hours,
            ),
            enforcement_service=EnforcementService(repository, cache=governance_cache),
            auto_enforce=not args.no_auto_enforce,
        )
        consumer = KafkaConsumer(
            kafka.bootstrap_servers,
            [kafka.risk_topic],
            group_id,
            f"{kafka.client_id}-governance-consumer",
            kafka.retry_topic,
            kafka.dead_letter_topic,
            kafka.security_protocol,
            kafka.max_retries,
            kafka.poll_timeout_seconds,
            kafka.producer_timeout_ms,
            args.offset_reset,
        )
        metrics = consumer.run(
            handler.handle,
            max_messages=args.max_messages,
            idle_timeout_seconds=args.idle_timeout,
        )
        if args.dispatch_outbox:
            outbox_result = OutboxDispatcher(
                repository,
                publisher,
                batch_size=governance.outbox_batch_size,
                max_attempts=governance.outbox_max_attempts,
            ).dispatch_all()
        status = KafkaAdmin(
            kafka.bootstrap_servers,
            kafka.client_id,
            kafka.security_protocol,
        ).consumer_group_status(group_id)
        return {
            "topic": kafka.risk_topic,
            "governance_topics": governance_topics,
            "group": status.to_dict(),
            "metrics": metrics.to_dict(),
            "outbox": outbox_result,
        }
    finally:
        if consumer is not None:
            consumer.close()
        if publisher is not None:
            publisher.close()
        if cache is not None:
            cache.close()
        engine.dispose()


def _run_governance_dispatch_outbox(args: argparse.Namespace) -> dict[str, Any]:
    from claro.application.outbox_dispatcher import OutboxDispatcher
    from claro.data_access.database import create_database_engine, create_session_factory
    from claro.data_access.repositories.governance_repository import GovernanceRepository
    from claro.infrastructure.kafka import KafkaAdmin, KafkaProducer

    settings = _kafka_enabled_settings()
    kafka = settings.kafka
    governance = settings.governance
    # Governance topics are created by the governance pipeline, but this command
    # can run standalone; ensure they exist before publishing outbox events.
    KafkaAdmin(
        kafka.bootstrap_servers,
        kafka.client_id,
        kafka.security_protocol,
    ).ensure_topics(
        list(governance.topics.all()),
        partitions=kafka.partitions,
        replication_factor=kafka.replication_factor,
    )
    engine = create_database_engine(settings)
    publisher = None
    try:
        publisher = KafkaProducer(
            kafka.bootstrap_servers,
            f"{kafka.client_id}-governance-outbox",
            kafka.security_protocol,
            kafka.producer_timeout_ms,
        )
        repository = GovernanceRepository(create_session_factory(engine))
        result = OutboxDispatcher(
            repository,
            publisher,
            batch_size=governance.outbox_batch_size,
            max_attempts=governance.outbox_max_attempts,
        ).dispatch_all(max_batches=max(args.max_batches, 1))
        return {**result, "outbox": repository.outbox_stats()}
    finally:
        if publisher is not None:
            publisher.close()
        engine.dispose()


def _run_governance_expire(args: argparse.Namespace) -> dict[str, Any]:
    with _governance_container() as container:
        expired = container.enforcement_service.expire_due_enforcements(limit=args.limit)
        return {"expired": expired, "limit": args.limit}


def _run_phase06_command(args: argparse.Namespace) -> int:
    """Dispatch the Phase 06 processing and demonstration commands."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from claro.application.message_events import RawGameMessagePayload
    from claro.bootstrap import create_app_container

    if args.command == "demo-clean" and not args.yes:
        print(
            "This deletes every record in the phase-06 demonstration dataset.\n"
            "The 50,000-message evaluation dataset is not touched.\n"
            "Re-run with --yes to confirm.",
            file=sys.stderr,
        )
        return 2

    container = create_app_container()
    try:
        if args.command == "demo-status":
            service = container.demo_service
            if service is None:
                print("demo service unavailable", file=sys.stderr)
                return 1
            _print_json(service.status())
            return 0
        if args.command == "demo-clean":
            service = container.demo_service
            if service is None:
                print("demo service unavailable", file=sys.stderr)
                return 1
            _print_json(service.clean(), args.output)
            return 0
        if args.command == "demo-run":
            service = container.demo_service
            if service is None:
                print("demo service unavailable", file=sys.stderr)
                return 1
            report = service.run()
            _print_json(report.to_dict(), args.output)
            return 0
        if args.command == "process-message":
            processing = container.processing_service
            if processing is None:
                print("processing service unavailable", file=sys.stderr)
                return 1
            if not args.text and not args.message:
                print("either --text or --message is required", file=sys.stderr)
                return 2
            if args.message:
                outcome = _reprocess_existing(container, args.message)
                _print_json(outcome, args.output)
                return 0 if outcome.get("status") not in {"failed"} else 1
            content = str(args.text)
            dataset_id = processing.resolve_dataset(args.dataset, seed=20261125)
            payload = RawGameMessagePayload(
                synthetic=True,
                dataset_id=dataset_id,
                dataset_name=args.dataset,
                dataset_seed=20261125,
                message_id=uuid4(),
                external_message_id=f"cli-{uuid4()}",
                trace_id=f"cli-{uuid4().hex[:12]}",
                player_ref=args.player,
                server_ref=args.server,
                alliance_ref=None,
                channel=args.channel,
                content=content,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                language="zh-CN",
                occurred_at=datetime.now(UTC),
            )
            outcome = processing.process_message(payload, publish=not args.no_publish)
            _print_json(outcome.to_dict(), args.output)
            return 0 if outcome.status in {"processed", "duplicate"} else 1
    finally:
        container.close()
    return 1


def _reprocess_existing(container, raw_message_id: str) -> dict[str, Any]:
    """Re-run detection and governance for a message that is already stored."""
    from datetime import UTC, datetime
    from uuid import UUID

    from claro.application.message_processing import ConsumedMessage
    from claro.application.risk_events import RiskAssessedPayload

    message_id = UUID(raw_message_id)
    risk_service = container.risk_service
    pipeline = container.governance_pipeline_service
    if risk_service is None or pipeline is None:
        raise RuntimeError("risk or governance service is unavailable")
    risk_service.detect(message_id, force=True)
    stored = risk_service.result(message_id)
    header = (
        container.explorer_service.detail(message_id)["header"]
        if container.explorer_service
        else None
    )
    event = RiskAssessedPayload.from_stored(
        stored, synthetic=bool(header and header["is_synthetic"])
    ).to_event(trace_id=f"reprocess-{message_id}")
    handling = pipeline.handle(
        ConsumedMessage(
            event=event,
            topic=container.settings.kafka.risk_topic,
            partition=0,
            offset=0,
            received_at=datetime.now(UTC),
            headers={},
        )
    )
    decision = container.governance_repository.decision_for_message(message_id)
    return {
        "message_id": str(message_id),
        "status": handling.status,
        "risk": stored.to_dict(),
        "decision": decision,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "check-config":
            settings = load_settings()
            print(f"Configuration valid: {settings.app.mode} mode")
            return 0
        if args.command == "info":
            _print_info()
            return 0
        if args.command == "check-db":
            from sqlalchemy import text

            from claro.data_access.database import create_database_engine

            settings = load_settings()
            engine = create_database_engine(settings)
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
            finally:
                engine.dispose()
            print("Database connection successful")
            return 0
        if args.command == "check-services":
            from claro.bootstrap import create_app_container

            container = create_app_container()
            try:
                results = [result.to_dict() for result in container.health_service.check_all()]
            finally:
                container.close()
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return 1 if any(result["status"] == "unhealthy" for result in results) else 0
        if args.command == "seed":
            from claro.data_access.database import (
                create_database_engine,
                create_session_factory,
            )
            from claro.data_access.seed import seed_synthetic_data
            from claro.infrastructure.logging import configure_logging

            settings = load_settings()
            configure_logging(settings)
            engine = create_database_engine(settings)
            try:
                result = seed_synthetic_data(create_session_factory(engine))
            finally:
                engine.dispose()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "generate-data":
            from claro.data_generation.generator import generate_synthetic_dataset

            generated = generate_synthetic_dataset(_generation_spec(args))
            _print_json(generated.summary(), args.output)
            return 0
        if args.command == "load-data":
            from claro.data_access.database import (
                create_database_engine,
                create_session_factory,
            )
            from claro.data_access.repositories.synthetic_repository import (
                load_generated_dataset,
            )
            from claro.data_generation.generator import generate_synthetic_dataset
            from claro.infrastructure.logging import configure_logging

            settings = load_settings()
            configure_logging(settings)
            generated = generate_synthetic_dataset(_generation_spec(args))
            engine = create_database_engine(settings)
            try:
                result = load_generated_dataset(
                    create_session_factory(engine),
                    generated,
                    batch_size=args.batch_size,
                    clean=args.clean,
                )
            finally:
                engine.dispose()
            _print_json(result)
            return 0
        if args.command == "clean-data":
            from claro.data_access.database import (
                create_database_engine,
                create_session_factory,
            )
            from claro.data_access.repositories.synthetic_repository import (
                delete_synthetic_dataset,
            )

            settings = load_settings()
            engine = create_database_engine(settings)
            try:
                result = delete_synthetic_dataset(create_session_factory(engine), args.dataset)
            finally:
                engine.dispose()
            _print_json(result)
            return 0
        if args.command == "check-data":
            from claro.data_access.database import (
                create_database_engine,
                create_session_factory,
            )
            from claro.data_access.repositories.synthetic_repository import (
                check_dataset_quality,
            )

            settings = load_settings()
            engine = create_database_engine(settings)
            try:
                result = check_dataset_quality(create_session_factory(engine), args.dataset)
            finally:
                engine.dispose()
            _print_json(result)
            return 0 if result["passed"] else 1
        if args.command == "warehouse-export":
            from claro.application.warehouse_export import export_postgresql
            from claro.data_access.database import (
                create_database_engine,
                create_session_factory,
            )

            since = None
            if args.since:
                since = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
            settings = load_settings()
            engine = create_database_engine(settings)
            try:
                result = export_postgresql(
                    create_session_factory(engine),
                    output_directory=args.output,
                    mode="full" if args.full else "incremental",
                    since=since,
                    dataset_name=args.dataset,
                    tables=tuple(args.tables),
                )
            finally:
                engine.dispose()
            _print_json(
                {
                    "mode": result.mode,
                    "output": str(result.output_directory),
                    "tables": result.tables,
                    "high_watermarks": result.high_watermarks,
                    "load_script": str(result.load_script),
                    "hive_sql_executed": False,
                }
            )
            return 0
        if args.command == "kafka-topics":
            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            _print_json(_run_kafka_topics())
            return 0
        if args.command == "kafka-produce":
            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            _print_json(_run_kafka_produce(args))
            return 0
        if args.command == "kafka-consume":
            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            _print_json(_run_kafka_consume(args))
            return 0
        if args.command == "kafka-group":
            _print_json(_run_kafka_group(args))
            return 0
        if args.command == "risk-status":
            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            with _risk_service() as (_settings, service):
                _print_json(service.status())
            return 0
        if args.command == "risk-sync-rules":
            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            with _risk_service() as (_settings, service):
                result = service.sync_rules()
                result["reload"] = service.reload_rules()
            _print_json(result, args.output)
            return 0
        if args.command == "risk-train":
            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            with _risk_service() as (_settings, service):
                result = service.train(args.dataset, args.algorithm)
            _print_json(result, args.output)
            return 0
        if args.command == "risk-evaluate":
            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            with _risk_service() as (_settings, service):
                result = service.evaluate(
                    args.dataset,
                    split=args.split,
                    model_id=args.model,
                    persist=not args.no_persist,
                )
            _print_json(result, args.output)
            return 0
        if args.command == "risk-detect":
            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            _print_json(_run_risk_detect(args), args.output)
            return 0
        if args.command == "risk-result":
            from uuid import UUID

            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            with _risk_service() as (_settings, service):
                _print_json(service.explain(UUID(args.message)), args.output)
            return 0
        if args.command == "risk-pipeline":
            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            _print_json(_run_risk_pipeline(args))
            return 0
        if args.command == "risk-cases":
            from uuid import UUID

            from claro.infrastructure.logging import configure_logging

            if args.limit < 1:
                raise ValueError("limit must be positive")
            configure_logging(load_settings())
            with _risk_service() as (_settings, service):
                run = service.evaluation(UUID(args.run))
                cases = service.evaluation_cases(UUID(args.run), args.type, limit=args.limit)
            _print_json({"run": run, "cases": cases}, args.output)
            return 0
        if args.command == "governance-seed-policies":
            from claro.application.policy_seed import seed_governance_policies
            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            with _governance_container() as container:
                result = seed_governance_policies(container.policy_service)
            _print_json(result)
            return 0
        if args.command == "governance-evaluate":
            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            _print_json(_run_governance_evaluate(args), args.output)
            return 0
        if args.command == "governance-decide":
            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            _print_json(_run_governance_decide(args), args.output)
            return 0
        if args.command == "governance-status":
            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            with _governance_container() as container:
                _print_json(container.governance_repository.governance_stats(), args.output)
            return 0
        if args.command == "governance-pipeline":
            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            _print_json(_run_governance_pipeline(args))
            return 0
        if args.command == "governance-dispatch-outbox":
            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            _print_json(_run_governance_dispatch_outbox(args), args.output)
            return 0
        if args.command == "governance-expire-enforcements":
            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            _print_json(_run_governance_expire(args), args.output)
            return 0
        if args.command in {"process-message", "demo-run", "demo-status", "demo-clean"}:
            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            return _run_phase06_command(args)
        if args.command.startswith("analytics-") or args.command == "strategy-replay":
            from claro.infrastructure.logging import configure_logging

            configure_logging(load_settings())
            _print_json(_run_analytics_command(args), getattr(args, "output", None))
            return 0
        if args.command == "serve":
            from claro.ui.app import run

            run()
            return 0
    except (OSError, ValueError, RuntimeError, SQLAlchemyError, KafkaException) as error:
        print(f"Claro startup failed: {error}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
