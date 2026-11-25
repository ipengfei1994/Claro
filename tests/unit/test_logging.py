from __future__ import annotations

from claro.infrastructure.logging import redact_sensitive


def test_sensitive_values_are_redacted() -> None:
    event = {
        "event": "connection",
        "password": "secret-value",
        "api_key": "key-value",
        "database_url": "postgresql+psycopg://claro:db-secret@localhost:5432/claro",
    }
    result = redact_sensitive(None, "info", event)
    assert result["password"] == "[REDACTED]"
    assert result["api_key"] == "[REDACTED]"
    assert "db-secret" not in result["database_url"]
    assert "claro:***@localhost" in result["database_url"]


def test_nested_sensitive_values_and_query_parameters_are_redacted() -> None:
    event = {
        "context": {
            "password": "nested-password",
            "items": [{"api_key": "nested-key"}, "safe"],
        },
        "database_url": (
            "postgresql+psycopg://claro:db-secret@localhost:5432/claro?password=query-secret&sslmode=require"
        ),
    }
    result = redact_sensitive(None, "info", event)
    assert result["context"]["password"] == "[REDACTED]"
    assert result["context"]["items"][0]["api_key"] == "[REDACTED]"
    assert "db-secret" not in result["database_url"]
    assert "query-secret" not in result["database_url"]
    assert "sslmode=require" in result["database_url"]
