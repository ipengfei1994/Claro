from __future__ import annotations

from pathlib import Path

import pytest

from claro.risk_engine.preprocessing import preprocess
from claro.risk_engine.rules import (
    RuleConfigurationError,
    RuleContext,
    RuleEngine,
    RuleProvider,
    load_rules,
)
from claro.risk_engine.taxonomy import RiskTaxonomy, load_taxonomy

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def taxonomy() -> RiskTaxonomy:
    return load_taxonomy(PROJECT_ROOT / "config" / "risk_taxonomy.yaml")


@pytest.fixture(scope="module")
def engine(taxonomy: RiskTaxonomy) -> RuleEngine:
    rules = load_rules(PROJECT_ROOT / "config" / "detection_rules.yaml", taxonomy)
    return RuleEngine(rules, taxonomy)


def rule_ids(result) -> set[str]:
    return {finding.rule_id for finding in result.findings if finding.rule_id}


def test_loads_all_configured_rules(engine: RuleEngine) -> None:
    assert len(engine.active_rules) == 22
    assert engine.version == 1


def test_keyword_rule_matches_normalized_text(engine: RuleEngine) -> None:
    result = engine.evaluate(preprocess("限时广告 立即点击 错过今天"))
    advertising = [item for item in result.findings if item.rule_id == "R-AD-001"]
    assert advertising
    assert advertising[0].category == "spam_advertising"
    assert advertising[0].db_category == "spam"
    assert advertising[0].evidence[0].text == "限时广告"


def test_negative_terms_suppress_rule(engine: RuleEngine) -> None:
    result = engine.evaluate(preprocess("请勿相信领取金币诈骗警示"))
    assert "R-FRD-001" not in rule_ids(result)
    assert result.stats["rules_suppressed"] >= 1


def test_blacklist_and_allow_list_urls(engine: RuleEngine) -> None:
    flagged = engine.evaluate(preprocess("看这个 https://scam-reward.invalid/x"))
    flagged_ids = rule_ids(flagged)
    assert "R-EXT-LINK-002" in flagged_ids
    assert "R-EXT-LINK-001" in flagged_ids

    allowed = engine.evaluate(preprocess("官方帮助 https://claro.example/help"))
    allowed_ids = rule_ids(allowed)
    assert "R-EXT-LINK-001" not in allowed_ids
    assert "R-EXT-LINK-002" not in allowed_ids


def test_phone_regex_evidence(engine: RuleEngine) -> None:
    result = engine.evaluate(preprocess("联系我 13800138000"))
    assert "R-EXT-CONTACT-002" in rule_ids(result)


def test_repetition_uses_segment_counts(engine: RuleEngine) -> None:
    result = engine.evaluate(preprocess("加群 加群 加群"))
    repetition = [item for item in result.findings if item.rule_id == "R-REP-001"]
    assert repetition
    assert any(span.text == "加群" for span in repetition[0].evidence)


def test_repetition_uses_recent_duplicate_history(engine: RuleEngine) -> None:
    result = engine.evaluate(preprocess("普通消息"), RuleContext(recent_duplicate_count=3))
    repetition = [item for item in result.findings if item.rule_id == "R-REP-001"]
    assert repetition
    assert repetition[0].evidence[0].source == "history"


def test_rejects_unknown_rule_category(taxonomy: RiskTaxonomy, tmp_path: Path) -> None:
    target = tmp_path / "rules.yaml"
    target.write_text(
        "version: 1\n"
        "rules:\n"
        "  - id: R-BAD-001\n"
        "    name: Bad rule\n"
        "    type: keyword\n"
        "    category: missing_category\n"
        "    severity: medium\n"
        "    weight: 0.5\n"
        "    priority: 10\n"
        "    status: active\n"
        "    version: 1\n"
        "    description: Invalid category.\n"
        "    terms: [测试]\n",
        encoding="utf-8",
    )
    with pytest.raises(RuleConfigurationError, match="unknown category"):
        load_rules(target, taxonomy)


def test_provider_reloads_when_file_changes(taxonomy: RiskTaxonomy, tmp_path: Path) -> None:
    source = (PROJECT_ROOT / "config" / "detection_rules.yaml").read_text(encoding="utf-8")
    target = tmp_path / "rules.yaml"
    target.write_text(source, encoding="utf-8")
    provider = RuleProvider(target, taxonomy)
    first = provider.load()
    assert first is provider.load()
    assert len(first.rules) == 22

    target.write_text(
        source.replace(
            "terms: [限时广告, 推广链接, 错过今天, 立即点击, 代练套餐]",
            "terms: [限时广告]",
        ),
        encoding="utf-8",
    )
    reloaded = provider.reload()
    assert reloaded is not first
    assert len(reloaded.rules) == 22
