from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from claro.application.warehouse_export import TABLES, export_postgresql
from claro.bootstrap import AppContainer


@pytest.mark.integration
def test_real_postgresql_warehouse_export(full_container: AppContainer, tmp_path: Path) -> None:
    result = export_postgresql(
        full_container.session_factory,
        output_directory=tmp_path,
        mode="full",
        dataset_name="phase-01-synthetic-v1",
    )
    assert result.tables["message"] == 3
    assert result.tables["policy_decision"] == 3
    assert result.tables["risk_event"] == 0
    assert result.tables["moderation_record"] == 0
    assert result.load_script.exists()
    load_sql = result.load_script.read_text(encoding="utf-8")
    assert "claro_ods.message" in load_sql
    assert "claro_ods.policy_decision" in load_sql
    assert "OVERWRITE" in load_sql

    message_files = list((tmp_path / "message").glob("dt=*/*.csv"))
    assert message_files
    with message_files[0].open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert list(rows[0]) == list(TABLES["message"].columns)
    assert all(row["is_synthetic"] == "true" for row in rows)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "full"
    assert manifest["high_watermarks"]["message"] is not None

    incremental = export_postgresql(
        full_container.session_factory,
        output_directory=tmp_path,
        mode="incremental",
        dataset_name="phase-01-synthetic-v1",
    )
    assert incremental.mode == "incremental"
    assert incremental.high_watermarks["message"] == result.high_watermarks["message"]
