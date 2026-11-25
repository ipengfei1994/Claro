from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from claro.application.warehouse_export import export_postgresql


def test_export_rejects_unknown_table(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown warehouse tables"):
        export_postgresql(Mock(), output_directory=tmp_path, mode="full", tables=("unknown",))


def test_incremental_export_requires_watermark(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires since"):
        export_postgresql(Mock(), output_directory=tmp_path, mode="incremental")


def test_export_rejects_naive_timestamp(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        export_postgresql(
            Mock(),
            output_directory=tmp_path,
            mode="incremental",
            since=datetime(2026, 11, 25),
        )
