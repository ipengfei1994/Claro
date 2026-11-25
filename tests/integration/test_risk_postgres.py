from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from claro.application.risk_service import RiskService
from claro.bootstrap import AppContainer
from claro.config.settings import load_settings
from claro.data_access.database import session_scope
from claro.data_access.models import Dataset, Message, RiskFinding, RiskResult
from claro.data_access.repositories.risk_repository import RiskRepository
from claro.data_access.repositories.synthetic_repository import delete_synthetic_dataset
from claro.domain.enums import MessageStatus


@pytest.mark.integration
def test_risk_detection_persists_on_postgresql(full_container: AppContainer) -> None:
    settings = load_settings()
    repository = RiskRepository(full_container.session_factory)
    service = RiskService(settings, repository)
    dataset_name = f"phase-02-synthetic-risk-it-{uuid4().hex[:10]}"
    content = "限时广告 立即点击 错过今天 https://scam-reward.invalid/x"
    with session_scope(full_container.session_factory) as session:
        dataset = Dataset(
            name=dataset_name,
            seed=20261125,
            generation_params={"synthetic": True, "template_version": 2},
            is_synthetic=True,
        )
        session.add(dataset)
        session.flush()
        dataset_id = dataset.id
        message = Message(
            dataset_id=dataset.id,
            external_message_id=f"risk-it-{uuid4().hex}",
            sender_ref="synthetic-risk-player",
            server_ref="s1",
            channel="world",
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            language="zh-CN",
            status=MessageStatus.RECEIVED.value,
            occurred_at=datetime.now(UTC),
            is_synthetic=True,
        )
        session.add(message)
        session.flush()
        message_id = message.id

    try:
        first = service.detect(message_id)
        assert first.created is True
        assert first.stored.risk_level in {"high", "critical"}
        assert "rule" in first.stored.detection_methods
        assert set(first.stored.detection_methods) <= {"rule", "ml"}
        assert first.stored.explanation["layers"][1]["layer"] == "ml"

        second = service.detect(message_id)
        assert second.created is False
        assert second.stored.risk_result_id == first.stored.risk_result_id

        with full_container.session_factory() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(RiskResult)
                    .where(RiskResult.dataset_id == dataset_id)
                )
                == 1
            )
            finding_count = session.scalar(
                select(func.count())
                .select_from(RiskFinding)
                .where(RiskFinding.message_id == message_id)
            )
            assert finding_count and finding_count > 0
            row = session.scalar(select(RiskResult).where(RiskResult.message_id == message_id))
            assert row is not None
            assert row.is_synthetic is True
            assert row.risk_level in {"high", "critical"}

        stats = repository.stats(dataset_name)
        assert stats["risk_results"] == 1
        assert stats["latency_ms"]["samples"] == 1
    finally:
        delete_synthetic_dataset(full_container.session_factory, dataset_name)
