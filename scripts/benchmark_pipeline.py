"""Phase 06 performance benchmark.

Measures the real pipeline against the live PostgreSQL / Kafka / Redis stack on
this machine. Nothing is simulated: every number below comes from a timed call
into product code, and the environment is recorded so the figures can be judged.

Design notes
------------
* The single-message pipeline (validate -> ingest -> detect -> publish ->
  governance) is expensive per call, so a *sample* of each tier is pushed through
  it and reported with p50/p95/p99 latency.
* Bulk ingestion (the throughput-critical stage) is measured over the full tier,
  because that is what a batch backfill actually costs.
* Benchmark rows are written to an isolated dataset and deleted afterwards.

Usage::

    .venv\\Scripts\\python.exe scripts\\benchmark_pipeline.py
    .venv\\Scripts\\python.exe scripts\\benchmark_pipeline.py --tiers 1000 --sample 100
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy import text  # noqa: E402

from claro.application.message_events import (  # noqa: E402
    RAW_GAME_MESSAGE_EVENT,
    RawGameMessagePayload,
)
from claro.data_access.repositories.kafka_repository import (  # noqa: E402
    ensure_dataset,
    event_payload_hash,
    persist_raw_message,
)

CORPUS = [
    "低价出售金币，走外部渠道，绕过官方，先付款后发货。",
    "你真是个废物，闭嘴吧，别在这里丢人。",
    "免费领取金币福利码，加微信 wx888999 领取奖励。",
    "今晚八点联盟集合，先把北门资源点拿下来，注意补兵。",
    "限时代练套餐五折优惠出售，立即点击下单私聊发货。",
    "我真的不想活了，想结束一切。",
    "外挂脚本代练，低价出金，私聊 telegram @claro_sell",
    "加我微信 wx888 免费领钻石，内部充值渠道一比十，先到先得。",
    "对面这波打得太菜了，笑死。",
    "出售账号，全英雄皮肤，走平台交易，价格可谈。",
]
BENCH_DATASET = "phase-06-benchmark"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tiers", default="1000,10000,50000")
    parser.add_argument("--sample", type=int, default=200, help="pipeline sample per tier")
    parser.add_argument("--keep", action="store_true", help="keep benchmark rows")
    parser.add_argument(
        "--queries-only",
        action="store_true",
        help="skip the tiers and only re-measure query latency on the current database",
    )
    parser.add_argument(
        "--validation-only",
        action="store_true",
        help="only measure payload schema-validation cost and merge it into the report",
    )
    args = parser.parse_args()
    tiers = [int(item) for item in args.tiers.split(",") if item.strip()]

    from claro.bootstrap import create_app_container

    container = create_app_container()
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": _environment(container),
        "tiers": [],
        "stages": {},
        "infrastructure": {},
        "queries": {},
    }
    try:
        if args.validation_only:
            _measure_validation(container, report)
        else:
            _measure_cache(container, report)
            if not args.queries_only:
                for tier in tiers:
                    print(f"\n=== tier {tier:,} ===", flush=True)
                    report["tiers"].append(_measure_tier(container, tier, args.sample))
                    # Clean each tier immediately so later query timings reflect the
                    # baseline database, not a database swollen by benchmark rows.
                    if not args.keep:
                        _cleanup(container)
            report["queries"] = _measure_queries(container)
            report["infrastructure"] = _measure_infrastructure(container)
    finally:
        if not args.keep:
            _cleanup(container)
        container.close()

    out_json = PROJECT_ROOT / "docs" / "performance_results.json"
    if (args.queries_only or args.validation_only) and out_json.exists():
        # Preserve the tier measurements from the full run; replace only what
        # this pass re-measured.
        previous = json.loads(out_json.read_text(encoding="utf-8"))
        previous["environment"] = report["environment"]
        if args.validation_only:
            previous.setdefault("stages", {}).update(report["stages"])
            previous["validation_measured_at"] = report["generated_at"]
        else:
            previous["queries"] = report["queries"]
            previous["infrastructure"] = report["infrastructure"]
            previous["stages"] = report["stages"]
            previous["queries_measured_at"] = report["generated_at"]
        report = previous
    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nresults written to {out_json}")
    _print_summary(report)
    return 0


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
def _environment(container: Any) -> dict[str, Any]:
    import importlib.metadata as metadata

    def version(package: str) -> str:
        try:
            return metadata.version(package)
        except metadata.PackageNotFoundError:
            return "n/a"

    settings = container.settings
    info: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()} ({platform.version()})",
        "machine": platform.machine(),
        "processor": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
        "cpu_logical": os.cpu_count(),
        "packages": {
            name: version(name)
            for name in (
                "streamlit",
                "plotly",
                "sqlalchemy",
                "psycopg",
                "confluent-kafka",
                "redis",
                "scikit-learn",
                "pandas",
                "pydantic",
            )
        },
        "mode": settings.app.mode,
        "db_pool": {
            "pool_size": settings.database.pool_size,
            "max_overflow": settings.database.max_overflow,
        },
    }
    try:
        import psutil

        info["memory_gb"] = round(psutil.virtual_memory().total / 1024**3, 1)
    except Exception:  # noqa: BLE001
        info["memory_gb"] = "psutil not installed"

    try:
        with container.engine.connect() as connection:
            info["postgresql"] = (
                connection.execute(text("SELECT version()")).scalar_one().split(" on ")[0]
            )
    except Exception as error:  # noqa: BLE001
        info["postgresql"] = f"unavailable: {error}"
    return info


# ---------------------------------------------------------------------------
# Payload generation
# ---------------------------------------------------------------------------
def _payloads(
    dataset_id: uuid.UUID, count: int, *, name: str = BENCH_DATASET, prefix: str = "bench"
) -> list[RawGameMessagePayload]:
    anchor = datetime.now(UTC).replace(microsecond=0)
    items: list[RawGameMessagePayload] = []
    for index in range(count):
        content = CORPUS[index % len(CORPUS)]
        items.append(
            RawGameMessagePayload(
                synthetic=True,
                dataset_id=dataset_id,
                dataset_name=name,
                dataset_seed=20261125,
                message_id=uuid.uuid5(uuid.NAMESPACE_URL, f"claro:bench:{prefix}:{index}"),
                external_message_id=f"{prefix}-{index:07d}",
                trace_id=f"bench-{index:07d}",
                player_ref=f"player.bench{index % 500:04d}",
                server_ref=f"s{100 + index % 20}",
                alliance_ref=None,
                channel=["world", "alliance", "private", "guild"][index % 4],
                content=content,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                language="zh-CN",
                occurred_at=anchor - timedelta(seconds=count - index),
            )
        )
    return items


def _stable_hash(payload: RawGameMessagePayload) -> str:
    """Content-addressed dedupe hash, identical in shape to the pipeline's own."""
    return event_payload_hash(
        {
            "event_id": str(payload.message_id),
            "event_type": RAW_GAME_MESSAGE_EVENT,
            "payload": payload.model_dump(mode="json"),
        }
    )


def _percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {}

    def pick(ratio: float) -> float:
        index = min(len(ordered) - 1, max(0, int(round(ratio * (len(ordered) - 1)))))
        return round(ordered[index], 2)

    return {
        "count": len(ordered),
        "avg_ms": round(statistics.fmean(ordered), 2),
        "p50_ms": pick(0.50),
        "p95_ms": pick(0.95),
        "p99_ms": pick(0.99),
        "max_ms": round(ordered[-1], 2),
        "min_ms": round(ordered[0], 2),
    }


# ---------------------------------------------------------------------------
# Tier measurement
# ---------------------------------------------------------------------------
def _measure_tier(container: Any, tier: int, sample: int) -> dict[str, Any]:
    dataset_name = f"{BENCH_DATASET}-{tier}"
    dataset_id = ensure_dataset(
        container.session_factory, name=dataset_name, seed=20261125, is_synthetic=True
    )
    payloads = _payloads(dataset_id, tier, name=dataset_name, prefix=f"t{tier}")

    # 1. Bulk ingestion over the full tier.
    started = time.perf_counter()
    for index, payload in enumerate(payloads):
        persist_raw_message(
            container.session_factory,
            payload,
            source_topic=f"claro.benchmark.{tier}.v1",
            source_partition=0,
            source_offset=index,
            payload_hash=_stable_hash(payload),
            sent_at=payload.occurred_at,
            received_at=datetime.now(UTC),
            attempts=1,
            transport="direct",
        )
    ingest_seconds = time.perf_counter() - started
    print(
        f"  ingest {tier:,} rows in {ingest_seconds:.1f}s ({tier / ingest_seconds:,.0f} rows/s)",
        flush=True,
    )

    # 2. Detection-only latency on a sample.
    risk = container.risk_service
    detect_latencies = []
    for payload in payloads[: min(sample, len(payloads))]:
        started = time.perf_counter()
        risk.analyze_text(payload.content)
        detect_latencies.append((time.perf_counter() - started) * 1000)

    # 3. Full pipeline on a sample, with per-stage timings.
    pipeline = container.processing_service
    pipeline_latencies: list[float] = []
    stage_totals: dict[str, list[float]] = {}
    statuses: dict[str, int] = {}
    for index, payload in enumerate(payloads[: min(sample, len(payloads))]):
        replacement = payload.model_copy(
            update={
                "message_id": uuid.uuid5(uuid.NAMESPACE_URL, f"claro:bench:pipe:{tier}:{index}"),
                "external_message_id": f"pipe-{tier}-{index:06d}",
                "trace_id": f"pipe-{tier}-{index:06d}",
            }
        )
        started = time.perf_counter()
        outcome = pipeline.process_message(replacement)
        pipeline_latencies.append((time.perf_counter() - started) * 1000)
        for stage in outcome.stages:
            stage_totals.setdefault(stage.name, []).append(stage.elapsed_ms)
        statuses[outcome.status] = statuses.get(outcome.status, 0) + 1

    pipeline_seconds = sum(pipeline_latencies) / 1000
    result = {
        "tier": tier,
        "bulk_ingest": {
            "rows": tier,
            "seconds": round(ingest_seconds, 2),
            "rows_per_second": round(tier / ingest_seconds, 1),
        },
        "detection": _percentiles(detect_latencies),
        "pipeline": _percentiles(pipeline_latencies),
        "pipeline_throughput_per_second": (
            round(len(pipeline_latencies) / pipeline_seconds, 2) if pipeline_seconds else None
        ),
        "pipeline_statuses": statuses,
        "stage_latency": {
            name: _percentiles(values) for name, values in sorted(stage_totals.items())
        },
    }
    print(
        f"  pipeline sample n={len(pipeline_latencies)} "
        f"p50={result['pipeline']['p50_ms']}ms p95={result['pipeline']['p95_ms']}ms "
        f"p99={result['pipeline']['p99_ms']}ms",
        flush=True,
    )
    return result


# ---------------------------------------------------------------------------
# Cache, queries, infrastructure
# ---------------------------------------------------------------------------
def _redis_client(container: Any) -> Any:
    cache = getattr(container.cache, "_client", None)
    return cache


def _measure_cache(container: Any, report: dict[str, Any]) -> None:
    client = _redis_client(container)
    if client is None:
        report["stages"]["redis"] = {"available": False}
        return
    before = client.info("stats")
    service = container.safety_cache
    if service is None:
        report["stages"]["redis"] = {"available": False}
        return
    started = time.perf_counter()
    for _ in range(50):
        service.sensitive_words()
    elapsed = time.perf_counter() - started
    after = client.info("stats")
    hits = after["keyspace_hits"] - before["keyspace_hits"]
    misses = after["keyspace_misses"] - before["keyspace_misses"]
    total = hits + misses
    report["stages"]["redis"] = {
        "available": True,
        "operations": 50,
        "elapsed_ms": round(elapsed * 1000, 2),
        "avg_ms": round(elapsed * 1000 / 50, 3),
        "keyspace_hits_delta": hits,
        "keyspace_misses_delta": misses,
        "hit_rate": round(hits / total, 4) if total else None,
        "redis_version": client.info("server").get("redis_version"),
        "used_memory_human": client.info("memory").get("used_memory_human"),
    }


def _measure_validation(container: Any, report: dict[str, Any]) -> None:
    """Measure the schema-validation cost that precedes the pipeline entry point.

    The pipeline records ``validate`` as a marker stage with 0 ms because the
    payload is already a validated model by the time ``process_message`` runs.
    The real cost is pydantic parsing the consumer's JSON dict, so it is timed
    here instead of being reported as zero.
    """
    dataset_id = ensure_dataset(
        container.session_factory,
        name=f"{BENCH_DATASET}-validation",
        seed=20261125,
        is_synthetic=True,
    )
    raws = [item.model_dump(mode="json") for item in _payloads(dataset_id, 1000)]
    latencies: list[float] = []
    for raw in raws:
        started = time.perf_counter()
        RawGameMessagePayload.from_json_mapping(raw)
        latencies.append((time.perf_counter() - started) * 1000)
    report["stages"]["validation"] = _percentiles(latencies)
    report["stages"]["validation"]["source"] = "RawGameMessagePayload.from_json_mapping"


def _measure_queries(container: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    explorer = container.explorer_service
    analytics = container.analytics_service

    started = time.perf_counter()
    explorer.overview(days=365)
    out["overview_service_ms"] = round((time.perf_counter() - started) * 1000, 1)

    started = time.perf_counter()
    explorer.search(page_size=25)
    out["search_page_25_ms"] = round((time.perf_counter() - started) * 1000, 1)

    started = time.perf_counter()
    explorer.risk_intelligence()
    out["risk_intelligence_ms"] = round((time.perf_counter() - started) * 1000, 1)

    if analytics is not None:
        from claro.analytics.filters import AnalyticsFilters

        end = datetime.now(UTC)
        filters = AnalyticsFilters(start=end - timedelta(days=365), end=end)
        started = time.perf_counter()
        analytics.overview(filters)
        out["analytics_overview_ms"] = round((time.perf_counter() - started) * 1000, 1)
        started = time.perf_counter()
        analytics.risk(filters)
        out["analytics_risk_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return out


def _measure_infrastructure(container: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        with container.engine.connect() as connection:
            out["db_size_bytes"] = connection.execute(
                text("SELECT pg_database_size(current_database())")
            ).scalar_one()
            out["message_rows"] = connection.execute(
                text("SELECT count(*) FROM message")
            ).scalar_one()
            out["risk_event_rows"] = connection.execute(
                text("SELECT count(*) FROM risk_event")
            ).scalar_one()
            out["policy_decision_rows"] = connection.execute(
                text("SELECT count(*) FROM policy_decision")
            ).scalar_one()
    except Exception as error:  # noqa: BLE001
        out["db_error"] = str(error)
    if container.producer is not None:
        started = time.perf_counter()
        try:
            container.publish_test_event()
            out["kafka_publish_ms"] = round((time.perf_counter() - started) * 1000, 1)
        except Exception as error:  # noqa: BLE001
            out["kafka_publish_error"] = str(error)
    return out


def _cleanup(container: Any) -> None:
    """Delete only the benchmark datasets and their dependent rows."""
    names = [f"{BENCH_DATASET}-%"]
    with container.engine.begin() as connection:
        dataset_ids = [
            row[0]
            for row in connection.execute(
                text("SELECT id FROM dataset WHERE name LIKE :pattern"), {"pattern": names[0]}
            )
        ]
        if not dataset_ids:
            return
        params = {"ids": dataset_ids}
        connection.execute(
            text(
                """
                DELETE FROM audit_event WHERE entity_id IN (
                    SELECT id FROM policy_decision WHERE dataset_id = ANY(:ids)
                    UNION SELECT id FROM risk_result WHERE dataset_id = ANY(:ids)
                    UNION SELECT id FROM moderation_case WHERE message_id IN
                        (SELECT id FROM message WHERE dataset_id = ANY(:ids))
                )
                """
            ),
            params,
        )
        for statement in (
            "DELETE FROM moderation_review WHERE case_id IN (SELECT id FROM moderation_case "
            "WHERE message_id IN (SELECT id FROM message WHERE dataset_id = ANY(:ids)))",
            "DELETE FROM case_event WHERE case_id IN (SELECT id FROM moderation_case "
            "WHERE message_id IN (SELECT id FROM message WHERE dataset_id = ANY(:ids)))",
            "DELETE FROM enforcement_action WHERE decision_id IN "
            "(SELECT id FROM policy_decision WHERE dataset_id = ANY(:ids))",
            "DELETE FROM policy_decision WHERE dataset_id = ANY(:ids)",
            "DELETE FROM risk_finding WHERE message_id IN "
            "(SELECT id FROM message WHERE dataset_id = ANY(:ids))",
            "DELETE FROM risk_event WHERE message_id IN "
            "(SELECT id FROM message WHERE dataset_id = ANY(:ids))",
            "DELETE FROM risk_result WHERE dataset_id = ANY(:ids)",
            "DELETE FROM moderation_case WHERE message_id IN "
            "(SELECT id FROM message WHERE dataset_id = ANY(:ids))",
            "DELETE FROM processing_event WHERE message_id IN "
            "(SELECT id FROM message WHERE dataset_id = ANY(:ids))",
            "DELETE FROM inbox_event WHERE event_id IN "
            "(SELECT id FROM message WHERE dataset_id = ANY(:ids))",
            "DELETE FROM message WHERE dataset_id = ANY(:ids)",
            "DELETE FROM dataset WHERE id = ANY(:ids)",
        ):
            connection.execute(text(statement), params)
    print("  benchmark rows removed")


def _print_summary(report: dict[str, Any]) -> None:
    print("\n--- summary ---")
    print(f"environment: {report['environment']['platform']} / {report['environment']['python']}")
    for tier in report["tiers"]:
        print(
            f"{tier['tier']:>7,} rows | "
            f"ingest {tier['bulk_ingest']['rows_per_second']:>10,.0f} rows/s"
            f" | pipeline p50 {tier['pipeline']['p50_ms']:>7.1f}ms"
            f" p95 {tier['pipeline']['p95_ms']:>7.1f}ms p99 {tier['pipeline']['p99_ms']:>7.1f}ms"
        )
    for name, value in report["queries"].items():
        print(f"query {name}: {value} ms")
    print(f"redis: {report['stages'].get('redis', {})}")


if __name__ == "__main__":
    raise SystemExit(main())
