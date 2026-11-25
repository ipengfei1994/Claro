from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from claro.config.settings import LLMSettings
from claro.risk_engine.preprocessing import PreprocessedText
from claro.risk_engine.types import DetectionFinding

logger = structlog.get_logger(__name__)

Transport = Callable[[str, dict[str, str], bytes, float], dict[str, Any]]


class LLMError(RuntimeError):
    pass


class LLMJudgement(BaseModel):
    risk: bool
    category: str | None = None
    severity: str | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=500)


@dataclass(frozen=True, slots=True)
class LLMResult:
    judgement: LLMJudgement
    model: str
    latency_ms: float
    attempts: int


@dataclass(frozen=True, slots=True)
class LLMConfig:
    enabled: bool
    base_url: str | None
    api_key: str | None
    model: str
    timeout_seconds: float
    max_retries: int
    max_input_chars: int

    @classmethod
    def from_settings(cls, settings: LLMSettings) -> LLMConfig:
        return cls(
            enabled=settings.enabled,
            base_url=settings.base_url,
            api_key=settings.api_key,
            model=settings.model,
            timeout_seconds=settings.timeout_seconds,
            max_retries=settings.max_retries,
            max_input_chars=settings.max_input_chars,
        )


class LLMAdapter:
    """Optional advisory layer; it never produces the final enforcement decision."""

    def __init__(self, config: LLMConfig, transport: Transport | None = None) -> None:
        self._config = config
        self._transport = transport or _http_transport
        self._logger = structlog.get_logger(__name__)

    @property
    def available(self) -> bool:
        return bool(self._config.enabled and self._config.base_url and self._config.api_key)

    @property
    def reason(self) -> str | None:
        if self.available:
            return None
        if not self._config.enabled:
            return "LLM layer disabled by configuration"
        return "LLM layer requires base_url and api_key"

    def analyze(
        self, text: PreprocessedText, findings: tuple[DetectionFinding, ...]
    ) -> LLMResult | None:
        if not self.available:
            return None
        payload = self._payload(text, findings)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        started = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(1, self._config.max_retries + 2):
            try:
                response = self._transport(
                    self._endpoint(), headers, body, self._config.timeout_seconds
                )
                judgement = _parse_judgement(response)
                latency = (time.perf_counter() - started) * 1000
                self._logger.info(
                    "llm_analysis_succeeded",
                    model=self._config.model,
                    attempt=attempt,
                    latency_ms=round(latency, 2),
                )
                return LLMResult(
                    judgement=judgement,
                    model=self._config.model,
                    latency_ms=latency,
                    attempts=attempt,
                )
            except (LLMError, OSError, TimeoutError, ValueError) as error:
                last_error = error
                self._logger.warning(
                    "llm_analysis_failed",
                    model=self._config.model,
                    attempt=attempt,
                    error=str(error),
                )
                if attempt <= self._config.max_retries:
                    time.sleep(min(2.0, 0.25 * 2 ** (attempt - 1)))
        raise LLMError(f"LLM analysis failed after retries: {last_error}")

    def _endpoint(self) -> str:
        base = (self._config.base_url or "").rstrip("/")
        return f"{base}/chat/completions"

    def _payload(
        self, text: PreprocessedText, findings: tuple[DetectionFinding, ...]
    ) -> dict[str, Any]:
        rule_categories = sorted({finding.category for finding in findings})
        message = text.original[: self._config.max_input_chars]
        prompt = (
            "Classify the following game chat message for content safety. "
            "Return only JSON with keys risk (boolean), category (taxonomy id or null), "
            "severity (low|medium|high|critical or null), confidence (0..1), rationale. "
            f"Rule engine categories: {rule_categories}. Message: {message}"
        )
        return {
            "model": self._config.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an advisory content-safety analyst. "
                        "You never decide enforcement. No player identifiers are provided."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }


def _parse_judgement(response: dict[str, Any]) -> LLMJudgement:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise LLMError("LLM response does not contain a chat completion") from error
    if not isinstance(content, str):
        raise LLMError("LLM response content is not text")
    try:
        data = json.loads(content)
        return LLMJudgement.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as error:
        raise LLMError(f"LLM response is not valid JSON: {error}") from error


def _http_transport(
    url: str, headers: dict[str, str], body: bytes, timeout: float
) -> dict[str, Any]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read()[:1_000].decode("utf-8", errors="replace")
        raise LLMError(f"LLM HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise LLMError(f"LLM request failed: {error.reason}") from error
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise LLMError("LLM HTTP response is not JSON") from error
    if not isinstance(payload, dict):
        raise LLMError("LLM HTTP response root is not an object")
    return payload
