from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool

from claro.config.settings import PROJECT_ROOT, ClaroSettings, redact_database_url
from claro.data_access.database import create_database_engine


def test_development_defaults_use_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLARO_APP__MODE", raising=False)
    settings = ClaroSettings(_env_file=None)
    assert settings.app.mode == "development"
    assert settings.database.url == "sqlite:///./data/claro-dev.db"
    assert not settings.redis.enabled
    assert not settings.kafka.enabled
    assert settings.ui.theme == "system"


def test_environment_overrides_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLARO_LOGGING__LEVEL", "DEBUG")
    settings = ClaroSettings(_env_file=None)
    assert settings.logging.level == "DEBUG"


def test_full_mode_requires_real_services(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLARO_APP__MODE", "full")
    monkeypatch.delenv("CLARO_DATABASE__URL", raising=False)
    monkeypatch.delenv("CLARO_REDIS__URL", raising=False)
    monkeypatch.delenv("CLARO_KAFKA__BOOTSTRAP_SERVERS", raising=False)
    with pytest.raises(ValidationError, match=r"postgresql\+psycopg"):
        ClaroSettings(_env_file=None)


def test_full_mode_accepts_native_service_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLARO_APP__MODE", "full")
    monkeypatch.setenv(
        "CLARO_DATABASE__URL",
        "postgresql+psycopg://claro:local-password@127.0.0.1:5432/claro",
    )
    monkeypatch.setenv("CLARO_REDIS__URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("CLARO_KAFKA__BOOTSTRAP_SERVERS", "127.0.0.1:9092")
    settings = ClaroSettings(_env_file=None)
    assert settings.app.mode == "full"
    assert settings.redis.enabled
    assert settings.kafka.enabled


def test_relative_paths_resolve_from_project_root() -> None:
    settings = ClaroSettings(_env_file=None)
    assert settings.resolved_log_directory().is_absolute()
    assert settings.resolved_database_url().startswith("sqlite:///")


def test_database_url_redaction_hides_password() -> None:
    redacted = redact_database_url("postgresql+psycopg://claro:super-secret@127.0.0.1:5432/claro")
    assert "super-secret" not in redacted
    assert "claro:***@127.0.0.1:5432" in redacted


def test_unknown_environment_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLARO_UNKNOWN__SETTING", "value")
    with pytest.raises(ValidationError):
        ClaroSettings(_env_file=None)


def test_ui_theme_accepts_supported_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLARO_UI__THEME", "dark")
    assert ClaroSettings(_env_file=None).ui.theme == "dark"

    monkeypatch.setenv("CLARO_UI__THEME", "high-contrast")
    with pytest.raises(ValidationError):
        ClaroSettings(_env_file=None)


def test_disabled_dotenv_does_not_select_full_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("CLARO_APP__MODE=full\n", encoding="utf-8")
    monkeypatch.setitem(ClaroSettings.model_config, "env_file", env_path)
    monkeypatch.delenv("CLARO_APP__MODE", raising=False)

    settings = ClaroSettings(_env_file=None)
    assert settings.app.mode == "development"


def test_full_mode_rejects_unsupported_database_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLARO_APP__MODE", "full")
    monkeypatch.setenv("CLARO_DATABASE__URL", "postgresql://claro:password@localhost/claro")
    monkeypatch.setenv("CLARO_REDIS__URL", "redis://localhost:6379/0")
    monkeypatch.setenv("CLARO_KAFKA__BOOTSTRAP_SERVERS", "localhost:9092")
    with pytest.raises(ValidationError, match=r"postgresql\+psycopg"):
        ClaroSettings(_env_file=None)


def test_relative_sqlite_paths_resolve_from_project_root() -> None:
    settings = ClaroSettings(_env_file=None, database={"url": "sqlite:///data/custom.db"})
    expected = f"sqlite:///{(PROJECT_ROOT / 'data' / 'custom.db').as_posix()}"
    assert settings.resolved_database_url() == expected


def test_sqlite_memory_urls_use_static_pool() -> None:
    for url in ("sqlite://", "sqlite:///:memory:"):
        settings = ClaroSettings(_env_file=None, database={"url": url})
        engine = create_database_engine(settings)
        try:
            assert isinstance(engine.pool, StaticPool)
        finally:
            engine.dispose()
