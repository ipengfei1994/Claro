"""Phase 06 reliability and security checks.

Each check exercises real code paths and prints PASS/FAIL with the evidence it
observed. Run with:  .venv\\Scripts\\python.exe scripts\\check_reliability.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}\n      {detail}")


def main() -> int:
    _unknown_env_rejected()
    _full_mode_requires_postgres()
    _placeholder_password_rejected()
    _secrets_redacted()
    _sql_injection_is_inert()
    _policy_expression_has_no_python()
    _sensitive_files_ignored()

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


def _unknown_env_rejected() -> None:
    """A misspelled CLARO_* variable must fail loudly instead of being ignored."""
    from claro.config.settings import load_settings

    os.environ["CLARO_TYPO_SETTING"] = "1"
    try:
        load_settings()
    except Exception as error:  # noqa: BLE001
        check(
            "unknown CLARO_* environment variable rejected", True, str(error).splitlines()[0][:160]
        )
    else:
        check("unknown CLARO_* environment variable rejected", False, "settings loaded anyway")
    finally:
        os.environ.pop("CLARO_TYPO_SETTING", None)


def _full_mode_requires_postgres() -> None:
    from claro.config.settings import ClaroSettings

    try:
        ClaroSettings.model_validate(
            {"app": {"mode": "full"}, "database": {"url": "sqlite:///x.db"}}
        )
    except Exception as error:  # noqa: BLE001
        check("full mode rejects a SQLite URL", True, str(error).splitlines()[1][:160])
    else:
        check("full mode rejects a SQLite URL", False, "validation passed unexpectedly")


def _placeholder_password_rejected() -> None:
    from claro.config.settings import ClaroSettings

    try:
        ClaroSettings.model_validate(
            {
                "app": {"mode": "full"},
                "database": {"url": "postgresql+psycopg://user:replace-me@127.0.0.1:5432/claro"},
                "redis": {"enabled": True, "url": "redis://127.0.0.1:6379/0"},
                "kafka": {"enabled": True, "bootstrap_servers": "127.0.0.1:9092"},
            }
        )
    except Exception as error:  # noqa: BLE001
        check("placeholder password rejected", True, str(error).splitlines()[1][:160])
    else:
        check("placeholder password rejected", False, "validation passed unexpectedly")


def _secrets_redacted() -> None:
    """Log records must never carry a password verbatim."""
    import structlog

    from claro.config.settings import load_settings
    from claro.infrastructure.logging import configure_logging

    settings = load_settings()
    configure_logging(settings)
    secret = "sup3r-secret-value"
    structlog.get_logger("claro.check").info("probe", api_key=secret, token=secret, password=secret)

    log_file = settings.resolved_log_directory() / "claro.jsonl"
    text = (
        log_file.read_text(encoding="utf-8", errors="ignore")[-4000:] if log_file.exists() else ""
    )
    ok = "probe" in text and secret not in text and "[REDACTED]" in text
    check(
        "secrets redacted from log output",
        ok,
        f"{log_file.name}: probe_written={'probe' in text} "
        f"raw_secret_present={secret in text} redaction_marker={'[REDACTED]' in text}",
    )


def _sql_injection_is_inert() -> None:
    """A hostile search term must be treated as data, not SQL."""
    from claro.bootstrap import create_app_container

    container = create_app_container()
    try:
        payloads = [
            "'; DROP TABLE message; --",
            "' OR 1=1 --",
            "%' UNION SELECT 1,2,3 --",
        ]
        for payload in payloads:
            page = container.explorer_service.search(text=payload, page_size=5)
            if page.total != 0:
                check(
                    "SQL injection payload treated as data",
                    False,
                    f"{payload!r} matched {page.total}",
                )
                return
        remaining = container.explorer_service.search(page_size=1).total
        check(
            "SQL injection payload treated as data",
            remaining > 0,
            f"3 payloads matched 0 rows; message table intact with {remaining} rows",
        )
    finally:
        container.close()


def _policy_expression_has_no_python() -> None:
    """Policy conditions are declarative data, not executable code."""
    patterns = {
        # Builtin eval/exec only: ``client.eval(...)`` (Redis Lua) and
        # ``model.eval()`` (torch) are method calls, not dynamic code execution.
        "builtin_eval": re.compile(r"(?<![.\w])eval\("),
        "builtin_exec": re.compile(r"(?<![.\w])exec\("),
        "dunder_import": re.compile(r"__import__"),
    }
    offenders = []
    for path in (PROJECT_ROOT / "src" / "claro").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in patterns.items():
            if pattern.search(text):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{name}")
    ok = not offenders
    check(
        "no dynamic code execution in governance paths",
        ok,
        "no eval/exec/__import__ found" if ok else ", ".join(offenders),
    )


def _sensitive_files_ignored() -> None:
    """`.env` and model artefacts must never be committed."""
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    ok = ".env" in gitignore
    check("local .env is git-ignored", ok, ".env present in .gitignore")


if __name__ == "__main__":
    raise SystemExit(main())
