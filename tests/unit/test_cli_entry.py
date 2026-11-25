"""CLI entry-point tests.

The CLI is the operator surface used by every PowerShell script, so two things
must never regress: ``python -m claro.cli`` has to actually execute, and status
payloads that contain UUIDs or datetimes have to print.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from uuid import uuid4

from claro.cli import _print_json, build_parser


def test_module_entry_point_runs() -> None:
    """``python -m claro.cli`` must execute ``main``, not just import it."""
    result = subprocess.run(
        [sys.executable, "-m", "claro.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()


def test_print_json_serialises_uuid_and_datetime(capsys) -> None:
    payload = {"id": uuid4(), "at": datetime(2026, 11, 25, 12, 0, tzinfo=UTC)}
    _print_json(payload)
    printed = json.loads(capsys.readouterr().out)
    assert set(printed) == {"id", "at"}
    assert isinstance(printed["id"], str) and len(printed["id"]) == 36
    assert printed["at"].startswith("2026-11-25T12:00")


def test_every_documented_command_parses() -> None:
    parser = build_parser()
    for command in (
        "check-config",
        "check-services",
        "info",
        "demo-status",
        "demo-run",
        "demo-clean",
        "process-message",
    ):
        args = parser.parse_args([command, *(["--yes"] if command == "demo-clean" else [])])
        assert args.command == command
