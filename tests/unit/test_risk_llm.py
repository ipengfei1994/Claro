from __future__ import annotations

import json

import pytest

from claro.risk_engine.llm import LLMAdapter, LLMConfig, LLMError
from claro.risk_engine.preprocessing import preprocess


def config(**overrides) -> LLMConfig:
    values = {
        "enabled": True,
        "base_url": "https://llm.example/v1",
        "api_key": "test-key",
        "model": "test-model",
        "timeout_seconds": 5.0,
        "max_retries": 0,
        "max_input_chars": 500,
    }
    values.update(overrides)
    return LLMConfig(**values)


def completion(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def test_disabled_adapter_is_unavailable_without_calling_transport() -> None:
    calls: list[tuple] = []

    def transport(*args):
        calls.append(args)
        return completion("{}")

    adapter = LLMAdapter(config(enabled=False), transport=transport)
    assert adapter.available is False
    assert adapter.reason == "LLM layer disabled by configuration"
    assert adapter.analyze(preprocess("测试消息"), ()) is None
    assert calls == []


def test_enabled_adapter_requires_credentials() -> None:
    adapter = LLMAdapter(config(api_key=None))
    assert adapter.available is False
    assert "base_url and api_key" in (adapter.reason or "")


def test_parses_advisory_judgement() -> None:
    captured: dict = {}

    def transport(url, headers, body, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json.loads(body)
        captured["timeout"] = timeout
        return completion(
            json.dumps(
                {
                    "risk": True,
                    "category": "fraud_fake_reward",
                    "severity": "high",
                    "confidence": 0.8,
                    "rationale": "synthetic test rationale",
                }
            )
        )

    adapter = LLMAdapter(config(), transport=transport)
    result = adapter.analyze(preprocess("领取金币 https://example.invalid"), ())

    assert result is not None
    assert result.judgement.risk is True
    assert result.judgement.category == "fraud_fake_reward"
    assert result.attempts == 1
    assert result.latency_ms >= 0
    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["timeout"] == 5.0
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["temperature"] == 0


def test_invalid_response_raises_after_retries() -> None:
    calls = 0

    def transport(*args):
        nonlocal calls
        calls += 1
        return completion("not-json")

    adapter = LLMAdapter(config(max_retries=0), transport=transport)
    with pytest.raises(LLMError, match="failed after retries"):
        adapter.analyze(preprocess("测试消息"), ())
    assert calls == 1


def test_missing_completion_is_rejected() -> None:
    adapter = LLMAdapter(config(), transport=lambda *args: {"choices": []})
    with pytest.raises(LLMError, match="chat completion"):
        adapter.analyze(preprocess("测试消息"), ())
