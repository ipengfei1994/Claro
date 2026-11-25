from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = PROJECT_ROOT / "config"


class AppSettings(BaseModel):
    mode: Literal["development", "full"] = "development"


class DatabaseSettings(BaseModel):
    url: str | None = None
    echo: bool = False
    pool_size: int = Field(default=5, ge=1)
    max_overflow: int = Field(default=10, ge=0)
    pool_timeout: int = Field(default=30, ge=1)


class RedisSettings(BaseModel):
    enabled: bool = False
    url: str | None = None
    socket_timeout: float = Field(default=3.0, gt=0)


class KafkaSettings(BaseModel):
    enabled: bool = False
    bootstrap_servers: str | None = None
    topic: str = "claro.content.events.v1"
    client_id: str = "claro"
    security_protocol: Literal["PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"] = "PLAINTEXT"
    raw_topic: str = "game.messages.raw"
    processed_topic: str = "game.messages.processed"
    risk_topic: str = "game.risk.events"
    moderation_topic: str = "game.moderation.events"
    retry_topic: str = "game.messages.retry"
    dead_letter_topic: str = "game.messages.dead-letter"
    consumer_group: str = "claro.pipeline.v1"
    retry_consumer_group: str = "claro.pipeline.retry.v1"
    partitions: int = Field(default=3, ge=1)
    replication_factor: int = Field(default=1, ge=1)
    producer_timeout_ms: int = Field(default=10_000, ge=1_000)
    max_retries: int = Field(default=3, ge=0)
    poll_timeout_seconds: float = Field(default=1.0, gt=0)


class LoggingSettings(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    directory: Path = Path("logs")
    json_output: bool = True
    max_bytes: int = Field(default=10_485_760, gt=0)
    backup_count: int = Field(default=5, ge=0)


class UISettings(BaseModel):
    port: int = Field(default=8501, ge=1, le=65535)
    theme: Literal["system", "light", "dark"] = "system"


class MLSettings(BaseModel):
    algorithm: Literal["logistic_regression", "linear_svm"] = "logistic_regression"
    models_dir: Path = Path("models")
    active_model_id: str | None = None
    min_df: int = Field(default=2, ge=1)
    max_features: int = Field(default=100_000, ge=1_000)
    ngram_min: int = Field(default=1, ge=1, le=4)
    ngram_max: int = Field(default=4, ge=1, le=6)
    c_values: list[float] = Field(default_factory=lambda: [1.0, 4.0], min_length=1)

    @model_validator(mode="after")
    def validate_ngrams(self) -> MLSettings:
        if self.ngram_min > self.ngram_max:
            raise ValueError("ngram_min must not exceed ngram_max")
        return self


class LLMSettings(BaseModel):
    enabled: bool = False
    base_url: str | None = None
    api_key: str | None = None
    model: str = "gpt-4o-mini"
    timeout_seconds: float = Field(default=15.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=5)
    max_input_chars: int = Field(default=4_000, ge=100, le=20_000)

    @model_validator(mode="after")
    def validate_credentials(self) -> LLMSettings:
        if self.enabled and (not self.base_url or not self.api_key):
            raise ValueError("enabled LLM adapter requires base_url and api_key")
        return self


class RiskSettings(BaseModel):
    taxonomy_file: Path = Path("config/risk_taxonomy.yaml")
    rules_file: Path = Path("config/detection_rules.yaml")
    thresholds_file: Path = Path("config/risk_thresholds.yaml")
    cache_ttl_seconds: int = Field(default=300, ge=1)
    duplicate_window_hours: int = Field(default=24, ge=1)
    max_batch_size: int = Field(default=200, ge=1)
    ml: MLSettings = Field(default_factory=MLSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)


class GovernanceTopicSettings(BaseModel):
    evaluated: str = "game.governance.evaluated.v1"
    decisions: str = "game.governance.decisions.v1"
    moderation: str = "game.governance.moderation.v1"
    enforcement: str = "game.governance.enforcement.v1"
    feedback: str = "game.governance.feedback.v1"

    def all(self) -> tuple[str, ...]:
        return (
            self.evaluated,
            self.decisions,
            self.moderation,
            self.enforcement,
            self.feedback,
        )


class GovernanceSettings(BaseModel):
    consumer_group: str = "claro.governance.v1"
    policy_cache_ttl_seconds: int = Field(default=60, ge=1)
    rate_limit_window_seconds: int = Field(default=60, ge=1)
    review_sla_hours: int = Field(default=24, ge=1)
    low_confidence_threshold: float = Field(default=0.55, ge=0, le=1)
    high_risk_confidence_threshold: float = Field(default=0.70, ge=0, le=1)
    outbox_batch_size: int = Field(default=100, ge=1)
    outbox_max_attempts: int = Field(default=5, ge=1)
    topics: GovernanceTopicSettings = Field(default_factory=GovernanceTopicSettings)


class ClaroSettings(BaseSettings):
    app: AppSettings = Field(default_factory=AppSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    ui: UISettings = Field(default_factory=UISettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    governance: GovernanceSettings = Field(default_factory=GovernanceSettings)

    model_config = SettingsConfigDict(
        env_prefix="CLARO_",
        env_nested_delimiter="__",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="forbid",
        validate_default=True,
        _nested_model_default_partial_update=True,
    )

    @model_validator(mode="after")
    def validate_mode_requirements(self) -> ClaroSettings:
        if self.app.mode == "development":
            if self.database.url and not self.database.url.startswith("sqlite:"):
                raise ValueError("development mode requires a SQLite database URL")
            if self.redis.enabled or self.kafka.enabled:
                raise ValueError("external adapters must be disabled in development mode")
        else:
            if not self.database.url or not self.database.url.startswith("postgresql+psycopg://"):
                raise ValueError(
                    "full mode requires CLARO_DATABASE__URL with a postgresql+psycopg:// URL"
                )
            if "replace-me" in self.database.url:
                raise ValueError("replace the database password placeholder in .env")
            if not self.redis.enabled or not self.redis.url:
                raise ValueError("full mode requires an enabled Redis adapter and URL")
            if not self.kafka.enabled or not self.kafka.bootstrap_servers:
                raise ValueError(
                    "full mode requires an enabled Kafka adapter and bootstrap servers"
                )
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml_settings = MergedYamlSettingsSource(settings_cls, init_settings(), dotenv_settings())
        strict_env_settings = StrictEnvironmentSettingsSource(settings_cls)
        return (
            init_settings,
            strict_env_settings,
            env_settings,
            dotenv_settings,
            yaml_settings,
            file_secret_settings,
        )

    def resolved_log_directory(self) -> Path:
        directory = self.logging.directory
        return directory if directory.is_absolute() else PROJECT_ROOT / directory

    def resolve_project_path(self, path: Path) -> Path:
        return path if path.is_absolute() else PROJECT_ROOT / path

    def resolved_models_dir(self) -> Path:
        return self.resolve_project_path(self.risk.ml.models_dir)

    def resolved_taxonomy_file(self) -> Path:
        return self.resolve_project_path(self.risk.taxonomy_file)

    def resolved_rules_file(self) -> Path:
        return self.resolve_project_path(self.risk.rules_file)

    def resolved_thresholds_file(self) -> Path:
        return self.resolve_project_path(self.risk.thresholds_file)

    def resolved_database_url(self) -> str:
        if not self.database.url:
            raise ValueError("database URL is not configured")
        url = self.database.url
        if url in {"sqlite://", "sqlite:///:memory:"}:
            return url
        prefix = "sqlite:///"
        if url.startswith(prefix):
            database_path, separator, query = url.removeprefix(prefix).partition("?")
            if not database_path.startswith("/"):
                path = Path(database_path)
                if not path.is_absolute():
                    resolved = (PROJECT_ROOT / path).as_posix()
                    return f"sqlite:///{resolved}{separator}{query}"
        return url


class StrictEnvironmentSettingsSource(PydanticBaseSettingsSource):
    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def prepare_field_value(
        self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool
    ) -> Any:
        return value

    def __call__(self) -> dict[str, Any]:
        allowed_keys: set[str] = set()
        for name, field in self.settings_cls.model_fields.items():
            prefix = f"CLARO_{name.upper()}"
            allowed_keys.add(prefix)
            annotation = field.annotation
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                for nested_name in annotation.model_fields:
                    allowed_keys.add(f"{prefix}__{nested_name.upper()}")

        unknown: dict[str, Any] = {}
        for key, value in os.environ.items():
            normalized_key = key.upper()
            if not normalized_key.startswith("CLARO_") or normalized_key in allowed_keys:
                continue
            path = normalized_key.removeprefix("CLARO_").lower().split("__")
            target = unknown
            for part in path[:-1]:
                target = target.setdefault(part, {})
            target[path[-1]] = value
        return unknown


class MergedYamlSettingsSource(PydanticBaseSettingsSource):
    def __init__(
        self,
        settings_cls: type[BaseSettings],
        init_data: dict[str, Any],
        dotenv_data: dict[str, Any],
    ) -> None:
        super().__init__(settings_cls)
        self._init_data = init_data
        self._dotenv_data = dotenv_data

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def prepare_field_value(
        self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool
    ) -> Any:
        return value

    def __call__(self) -> dict[str, Any]:
        mode = self._requested_mode()
        default_data = self._read_yaml("default.yaml")
        mode_data = self._read_yaml(f"{mode}.yaml")
        return _deep_merge(default_data, mode_data)

    def _requested_mode(self) -> str:
        for data in (
            self._init_data,
            {"app": {"mode": os.getenv("CLARO_APP__MODE")}},
            self._dotenv_data,
        ):
            app_data = data.get("app", {})
            if app_data.get("mode"):
                return str(app_data["mode"])
        return "development"

    @staticmethod
    def _read_yaml(filename: str) -> dict[str, Any]:
        path = CONFIG_DIR / filename
        if not path.is_file():
            raise FileNotFoundError(f"configuration file not found: {path}")
        with path.open("r", encoding="utf-8") as stream:
            data = yaml.safe_load(stream) or {}
        if not isinstance(data, dict):
            raise ValueError(f"configuration root must be a mapping: {path}")
        return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_settings() -> ClaroSettings:
    return ClaroSettings()


def redact_database_url(url: str) -> str:
    parts = urlsplit(url)
    userinfo, separator, host_port = parts.netloc.rpartition("@")
    if separator:
        username, password_separator, _ = userinfo.partition(":")
        masked = f"{username}:***@" if password_separator else f"{username}@"
        netloc = f"{masked}{host_port}"
    else:
        netloc = parts.netloc

    query = parts.query
    if query:
        parameters = parse_qsl(query, keep_blank_values=True)
        if any(_is_sensitive_query_key(key) for key, _ in parameters):
            query = urlencode(
                [
                    (key, "[REDACTED]" if _is_sensitive_query_key(key) else value)
                    for key, value in parameters
                ]
            )
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def _is_sensitive_query_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(
        marker in normalized
        for marker in (
            "password",
            "passwd",
            "token",
            "secret",
            "authorization",
            "api_key",
            "apikey",
        )
    )
