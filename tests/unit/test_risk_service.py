from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from claro.application.risk_service import RiskService, RiskServiceError
from claro.config.settings import ClaroSettings
from claro.data_access.database import (
    create_database_engine,
    create_session_factory,
    session_scope,
)
from claro.data_access.models import (
    Base,
    Dataset,
    DetectionRule,
    Message,
    RiskFinding,
)
from claro.data_access.repositories.risk_repository import RiskRepository
from claro.domain.enums import MessageStatus


@dataclass
class RiskEnvironment:
    settings: ClaroSettings
    engine: object
    session_factory: object
    repository: RiskRepository
    service: RiskService
    dataset_id: UUID
    dataset_name: str


@pytest.fixture
def risk_env() -> RiskEnvironment:
    settings = ClaroSettings(
        _env_file=None,
        app={"mode": "development"},
        database={"url": "sqlite:///:memory:"},
        redis={"enabled": False},
        kafka={"enabled": False},
    )
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    repository = RiskRepository(factory)
    dataset_name = f"unit-risk-{uuid4().hex[:8]}"
    with session_scope(factory) as session:
        dataset = Dataset(
            name=dataset_name,
            seed=20261125,
            generation_params={"synthetic": True, "size": 10},
            is_synthetic=True,
        )
        session.add(dataset)
        session.flush()
        dataset_id = dataset.id
    environment = RiskEnvironment(
        settings=settings,
        engine=engine,
        session_factory=factory,
        repository=repository,
        service=RiskService(settings, repository),
        dataset_id=dataset_id,
        dataset_name=dataset_name,
    )
    try:
        yield environment
    finally:
        engine.dispose()


def add_message(
    env: RiskEnvironment,
    content: str,
    *,
    sender: str = "player-1",
    occurred_at: datetime | None = None,
    external_id: str | None = None,
    status: str | None = None,
) -> UUID:
    timestamp = occurred_at or datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
    with session_scope(env.session_factory) as session:
        message = Message(
            dataset_id=env.dataset_id,
            external_message_id=external_id or f"ext-{uuid4().hex}",
            sender_ref=sender,
            server_ref="s1",
            channel="world",
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            language="zh-CN",
            status=status or MessageStatus.RECEIVED.value,
            occurred_at=timestamp,
            is_synthetic=True,
        )
        session.add(message)
        session.flush()
        return message.id


def test_detection_persists_and_is_idempotent(risk_env: RiskEnvironment) -> None:
    message_id = add_message(
        risk_env,
        "限时广告 立即点击 错过今天 看 https://scam-reward.invalid/x",
    )
    with session_scope(risk_env.session_factory) as session:
        session.add(
            RiskFinding(
                message_id=message_id,
                detector="synthetic-rule-engine",
                detector_version="phase-02",
                category="other",
                score=0.5,
                confidence=0.5,
                evidence={"legacy": True},
            )
        )

    first = risk_env.service.detect(message_id)
    assert first.created is True
    assert first.stored.risk_level == "critical"
    assert first.stored.suggested_action == "restrict"
    assert first.stored.detection_methods == ["rule"]
    assert first.stored.explanation["question_answers"]
    assert set(first.stored.explanation["question_answers"]) >= {
        "why_flagged",
        "matched_rules",
        "evidence",
        "score_formation",
        "level_decision",
        "conflicts",
    }

    second = risk_env.service.detect(message_id)
    assert second.created is False
    assert second.stored.risk_result_id == first.stored.risk_result_id

    findings = risk_env.repository.findings(message_id)
    assert findings
    assert all(item["detector"].startswith("rule.") for item in findings)
    assert all(item["detector"] != "synthetic-rule-engine" for item in findings)
    assert any(item["evidence"]["spans"] for item in findings if item["category"] == "spam")

    stats = risk_env.repository.stats(risk_env.dataset_name)
    assert stats["risk_results"] == 1
    assert stats["levels"] == {"critical": 1}

    explained = risk_env.service.explain(message_id)
    assert explained["risk_result"]["risk_result_id"] == str(first.stored.risk_result_id)
    assert all(item["detector"] != "synthetic-rule-engine" for item in explained["findings"])


def test_detection_uses_recent_duplicate_history(risk_env: RiskEnvironment) -> None:
    base = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
    for minutes in (10, 5, 1):
        add_message(
            risk_env,
            "普通消息内容",
            sender="player-dup",
            occurred_at=base - timedelta(minutes=minutes),
        )
    target = add_message(risk_env, "普通消息内容", sender="player-dup", occurred_at=base)

    record = risk_env.service.detect(target)
    assert record.created is True
    findings = risk_env.repository.findings(target)
    repetition = [item for item in findings if item["detector"] == "rule.repetition"]
    assert repetition
    spans = repetition[0]["evidence"]["spans"]
    assert any(span["source"] == "history" for span in spans)
    assert any(span["text"] == "recent_duplicates=3" for span in spans)


def test_sync_rules_preserves_unmanaged_rules(risk_env: RiskEnvironment) -> None:
    with session_scope(risk_env.session_factory) as session:
        session.add(
            DetectionRule(
                dataset_id=None,
                rule_key="legacy-rule",
                version=1,
                rule_type="keyword",
                definition={"terms": ["旧词"]},
                status="active",
                is_synthetic=False,
            )
        )

    first = risk_env.service.sync_rules()
    assert first["created"] == 22
    assert first["updated"] == 0
    assert first["disabled"] == 0

    second = risk_env.service.sync_rules()
    assert second["created"] == 0
    assert second["updated"] == 22
    assert second["disabled"] == 0

    with session_scope(risk_env.session_factory) as session:
        legacy = session.query(DetectionRule).filter_by(rule_key="legacy-rule").one()
        assert legacy.status == "active"
        synced = session.query(DetectionRule).filter_by(rule_key="R-AD-001").one()
        assert synced.status == "active"
        assert synced.definition["managed_by"] == "detection_rules.yaml"

    status = risk_env.service.status(risk_env.dataset_name)
    assert status["rules"]["rules"] == 22
    assert status["model"]["loaded"] is None
    assert "no active model" in (status["model"]["degraded_reason"] or "")
    assert status["semantic"]["status"] == "not_available"
    assert status["llm"]["status"] == "disabled"


def test_unknown_message_raises(risk_env: RiskEnvironment) -> None:
    with pytest.raises(RiskServiceError, match="message not found"):
        risk_env.service.detect(uuid4())
