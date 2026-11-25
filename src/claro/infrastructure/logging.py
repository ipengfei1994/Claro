from __future__ import annotations

import logging
import logging.handlers
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog
from structlog.typing import EventDict, Processor

from claro.config.settings import ClaroSettings, redact_database_url

_SENSITIVE_MARKERS = ("password", "token", "secret", "authorization", "api_key")


def redact_sensitive(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> EventDict:
    for key in list(event_dict):
        event_dict[key] = _redact_field(key, event_dict[key])
    return event_dict


def _redact_field(key: Any, value: Any) -> Any:
    normalized = str(key).lower().replace("-", "_")
    if any(marker in normalized for marker in _SENSITIVE_MARKERS):
        return "[REDACTED]"
    if normalized.endswith("database_url") and isinstance(value, str):
        return redact_database_url(value)
    return _redact_nested(value)


def _redact_nested(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _redact_field(key, item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_nested(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_nested(item) for item in value)
    return value


def configure_logging(settings: ClaroSettings) -> None:
    log_directory = settings.resolved_log_directory()
    log_directory.mkdir(parents=True, exist_ok=True)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        redact_sensitive,
    ]
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if settings.logging.json_output
        else structlog.dev.ConsoleRenderer()
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    file_handler = logging.handlers.RotatingFileHandler(
        log_directory / "claro.jsonl",
        maxBytes=settings.logging.max_bytes,
        backupCount=settings.logging.backup_count,
        encoding="utf-8",
        delay=True,
    )
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.setLevel(settings.logging.level)

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
