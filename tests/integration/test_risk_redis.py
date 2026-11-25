from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from claro.bootstrap import AppContainer
from claro.risk_engine.rules import RULE_CACHE_KEY, RuleProvider
from claro.risk_engine.taxonomy import load_taxonomy

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_rule_set_is_cached_in_redis(full_container: AppContainer) -> None:
    cache = full_container.cache
    assert cache is not None
    taxonomy = load_taxonomy(PROJECT_ROOT / "config" / "risk_taxonomy.yaml")
    path = PROJECT_ROOT / "config" / "detection_rules.yaml"
    provider = RuleProvider(path, taxonomy, cache=cache, cache_ttl_seconds=30)
    cache.delete(RULE_CACHE_KEY)
    try:
        rules = provider.load()
        assert len(rules.rules) == 22

        raw = cache.get(RULE_CACHE_KEY)
        assert raw is not None
        payload = json.loads(raw)
        expected_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert payload["digest"] == expected_digest
        assert payload["version"] == rules.version
        assert len(payload["rules"]) == 22

        second = RuleProvider(path, taxonomy, cache=cache, cache_ttl_seconds=30)
        assert second.load() == rules

        reloaded = provider.reload()
        assert len(reloaded.rules) == 22
        assert cache.get(RULE_CACHE_KEY) is not None
    finally:
        cache.delete(RULE_CACHE_KEY)
