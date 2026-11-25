from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from claro.data_access.database import session_scope


@dataclass(frozen=True, slots=True)
class TableExport:
    name: str
    columns: tuple[str, ...]
    query: str
    watermark_column: str
    watermark_sql: str


TABLES: dict[str, TableExport] = {
    "message": TableExport(
        "message",
        (
            "message_id",
            "dataset_id",
            "dataset_name",
            "external_message_id",
            "sender_ref",
            "server_ref",
            "channel",
            "content",
            "content_hash",
            "language",
            "status",
            "occurred_at",
            "ingested_at",
            "is_synthetic",
            "source_updated_at",
        ),
        """
        SELECT m.id AS message_id, m.dataset_id, d.name AS dataset_name,
               m.external_message_id, m.sender_ref, m.server_ref, m.channel,
               m.content, m.content_hash, m.language, m.status, m.occurred_at,
               m.ingested_at, m.is_synthetic, m.ingested_at AS source_updated_at
        FROM message m LEFT JOIN dataset d ON d.id = m.dataset_id
        """,
        "source_updated_at",
        "m.ingested_at",
    ),
    "risk_event": TableExport(
        "risk_event",
        (
            "risk_event_id",
            "dataset_id",
            "dataset_name",
            "message_id",
            "rule_id",
            "category",
            "event_type",
            "risk_score",
            "confidence",
            "severity",
            "occurred_at",
            "details_json",
            "is_synthetic",
            "source_updated_at",
        ),
        """
        SELECT r.id AS risk_event_id, r.dataset_id, d.name AS dataset_name,
               r.message_id, r.rule_id, r.category, r.event_type, r.risk_score,
               r.confidence, r.severity, r.occurred_at,
               r.details::text AS details_json, r.is_synthetic,
               r.created_at AS source_updated_at
        FROM risk_event r JOIN dataset d ON d.id = r.dataset_id
        """,
        "source_updated_at",
        "r.created_at",
    ),
    "policy_decision": TableExport(
        "policy_decision",
        (
            "decision_id",
            "dataset_id",
            "dataset_name",
            "message_id",
            "policy_id",
            "action",
            "risk_score",
            "reason_codes_json",
            "decided_at",
            "is_synthetic",
            "source_updated_at",
        ),
        """
        SELECT p.id AS decision_id, p.dataset_id, d.name AS dataset_name,
               p.message_id, p.policy_id, p.action, p.risk_score,
               p.reason_codes::text AS reason_codes_json, p.decided_at,
               p.is_synthetic, p.created_at AS source_updated_at
        FROM policy_decision p
        JOIN message pm ON pm.id = p.message_id
        LEFT JOIN dataset d ON d.id = COALESCE(p.dataset_id, pm.dataset_id)
        """,
        "source_updated_at",
        "p.created_at",
    ),
    "moderation_record": TableExport(
        "moderation_record",
        (
            "moderation_record_id",
            "dataset_id",
            "dataset_name",
            "message_id",
            "case_id",
            "idempotency_key",
            "action",
            "actor_type",
            "actor_ref",
            "risk_score",
            "reason_codes_json",
            "note",
            "occurred_at",
            "is_synthetic",
            "source_updated_at",
        ),
        """
        SELECT mr.id AS moderation_record_id, mr.dataset_id, d.name AS dataset_name,
               mr.message_id, mr.case_id, mr.idempotency_key, mr.action,
               mr.actor_type, mr.actor_ref, mr.risk_score,
               mr.reason_codes::text AS reason_codes_json, mr.note,
               mr.occurred_at, mr.is_synthetic, mr.created_at AS source_updated_at
        FROM moderation_record mr JOIN dataset d ON d.id = mr.dataset_id
        """,
        "source_updated_at",
        "mr.created_at",
    ),
}


@dataclass(frozen=True, slots=True)
class WarehouseExportResult:
    mode: str
    output_directory: Path
    tables: dict[str, int]
    high_watermarks: dict[str, str | None]
    load_script: Path


def export_postgresql(
    session_factory: sessionmaker[Session],
    *,
    output_directory: Path,
    mode: str,
    since: datetime | None = None,
    dataset_name: str | None = None,
    tables: tuple[str, ...] = tuple(TABLES),
) -> WarehouseExportResult:
    if mode not in {"full", "incremental"}:
        raise ValueError("mode must be full or incremental")
    unknown = set(tables) - set(TABLES)
    if unknown:
        raise ValueError(f"unknown warehouse tables: {sorted(unknown)}")
    output_directory.mkdir(parents=True, exist_ok=True)
    manifest_path = output_directory / "manifest.json"
    previous = _read_manifest(manifest_path)
    if mode == "incremental" and since is None and not previous.get("high_watermarks"):
        raise ValueError("incremental export requires since or an existing manifest")
    if since is not None and since.tzinfo is None:
        raise ValueError("since must be timezone-aware")

    batch_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
    counts: dict[str, int] = {}
    high_watermarks = dict(previous.get("high_watermarks", {}))
    load_statements: list[str] = []

    for table_name in tables:
        spec = TABLES[table_name]
        table_since = since
        if mode == "incremental" and table_since is None:
            stored = previous.get("high_watermarks", {}).get(table_name)
            if stored is None:
                stored = previous.get("exported_at")
            if not isinstance(stored, str):
                raise ValueError(f"no incremental watermark for {table_name}; provide --since")
            table_since = datetime.fromisoformat(stored)
        conditions: list[str] = []
        parameters: dict[str, Any] = {}
        if mode == "incremental":
            assert table_since is not None
            conditions.append(f"{spec.watermark_sql} >= :since")
            parameters["since"] = table_since
        if dataset_name is not None:
            conditions.append("d.name = :dataset_name")
            parameters["dataset_name"] = dataset_name
        query = spec.query
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += f" ORDER BY {spec.watermark_sql}"
        count, watermark = _export_table(
            session_factory, spec, query, parameters, output_directory, batch_id
        )
        counts[table_name] = count
        previous_watermark = previous.get("high_watermarks", {}).get(table_name)
        high_watermarks[table_name] = _latest_timestamp(previous_watermark, watermark)

        if count:
            partition_directory = output_directory / table_name
            for partition in sorted(partition_directory.glob(f"dt=*/{batch_id}.csv")):
                dt = partition.parent.name.removeprefix("dt=")
                overwrite = " OVERWRITE" if mode == "full" else ""
                local_path = partition.resolve().as_uri()
                columns = ", ".join(spec.columns)
                load_statements.append(
                    f"LOAD DATA LOCAL INPATH '{_escape_hive_string(local_path)}'{overwrite} "
                    f"INTO TABLE claro_ods.{table_name} PARTITION (dt='{dt}') "
                    f"({columns});"
                )

    manifest = {
        "batch_id": batch_id,
        "mode": mode,
        "dataset_name": dataset_name,
        "since": since.astimezone(UTC).isoformat() if since else None,
        "exported_at": datetime.now(UTC).isoformat(),
        "counts": counts,
        "high_watermarks": high_watermarks,
        "synthetic_notice": "Exported rows retain their source is_synthetic markers.",
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    load_script = output_directory / "load_ods.sql"
    load_script.write_text(
        "-- Generated PostgreSQL export; review before execution.\n"
        + ("\n".join(load_statements) or "-- No rows exported.")
        + "\n",
        encoding="utf-8",
    )
    return WarehouseExportResult(
        mode=mode,
        output_directory=output_directory,
        tables=counts,
        high_watermarks=high_watermarks,
        load_script=load_script,
    )


def _export_table(
    session_factory: sessionmaker[Session],
    spec: TableExport,
    query: str,
    parameters: dict[str, Any],
    output_directory: Path,
    batch_id: str,
) -> tuple[int, datetime | None]:
    count = 0
    watermark: datetime | None = None
    writers: dict[str, tuple[Any, Any]] = {}
    try:
        with session_scope(session_factory) as session:
            rows = session.execute(
                text(query).execution_options(stream_results=True), parameters
            ).mappings()
            for row in rows:
                source_updated_at = _aware(row[spec.watermark_column])
                event_time = _aware(row.get("occurred_at") or row.get("decided_at"))
                if event_time is None:
                    raise ValueError(f"{spec.name} row has no event timestamp")
                dt = event_time.strftime("%Y-%m-%d")
                if dt not in writers:
                    directory = output_directory / spec.name / f"dt={dt}"
                    directory.mkdir(parents=True, exist_ok=True)
                    handle = (directory / f"{batch_id}.csv").open("w", encoding="utf-8", newline="")
                    writer = csv.writer(
                        handle,
                        delimiter=",",
                        quotechar='"',
                        doublequote=False,
                        escapechar="\\",
                        quoting=csv.QUOTE_ALL,
                        lineterminator="\n",
                    )
                    writer.writerow(spec.columns)
                    writers[dt] = (handle, writer)
                writers[dt][1].writerow([_csv_value(row[column]) for column in spec.columns])
                count += 1
                if watermark is None or source_updated_at > watermark:
                    watermark = source_updated_at
    finally:
        for handle, _ in writers.values():
            handle.close()
    return count, watermark


def _csv_value(value: Any) -> str:
    if value is None:
        return r"\N"
    if isinstance(value, datetime):
        return _aware(value).isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("warehouse manifest must contain a JSON object")
    return value


def _latest_timestamp(previous: Any, current: datetime | None) -> str | None:
    candidates = []
    if isinstance(previous, str):
        candidates.append(datetime.fromisoformat(previous))
    if current is not None:
        candidates.append(current)
    return max(candidates).astimezone(UTC).isoformat() if candidates else None


def _escape_hive_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "''")
