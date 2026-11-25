from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from claro.bootstrap import AppContainer, create_app_container
from claro.config.settings import load_settings
from claro.data_access.database import session_scope
from claro.data_access.models import (
    AuditEvent,
    Dataset,
    Message,
    OutboxEvent,
    PlayerEnforcementState,
    Policy,
    PolicyVersion,
)
from claro.data_access.repositories.synthetic_repository import delete_synthetic_dataset
from claro.domain.enums import MessageStatus


@pytest.fixture
def full_container() -> Iterator[AppContainer]:
    settings = load_settings()
    if settings.app.mode != "full":
        pytest.fail(
            "Integration tests require full mode and real PostgreSQL, Redis, and Kafka services. "
            "Configure .env or CLARO_* environment variables before running them."
        )
    container = create_app_container(settings)
    try:
        yield container
    finally:
        container.close()


@pytest.fixture
def governance_data(full_container: AppContainer) -> Iterator[dict[str, Any]]:
    """Create an isolated synthetic message with a real risk result for governance tests.

    All rows are marked synthetic and removed in teardown so repeated runs do
    not contaminate the shared demonstration database.
    """
    suffix = uuid4().hex[:12]
    dataset_name = f"phase-02-synthetic-gov-it-{suffix}"
    policy_prefix = f"gov-it-{suffix}-"
    sender_ref = f"synthetic-gov-player-{suffix}"
    content = "限时福利 免费领取金币 https://scam-reward.invalid/x"
    with session_scope(full_container.session_factory) as session:
        dataset = Dataset(
            name=dataset_name,
            seed=20261125,
            generation_params={
                "synthetic": True,
                "template_version": 2,
                "purpose": "governance-it",
            },
            is_synthetic=True,
        )
        session.add(dataset)
        session.flush()
        message = Message(
            dataset_id=dataset.id,
            external_message_id=f"gov-it-{suffix}",
            sender_ref=sender_ref,
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

    detection = full_container.risk_service.detect(message_id)
    data: dict[str, Any] = {
        "suffix": suffix,
        "dataset_name": dataset_name,
        "policy_prefix": policy_prefix,
        "message_id": message_id,
        "sender_ref": sender_ref,
        "content": content,
        "risk_result_id": detection.stored.risk_result_id,
    }
    try:
        yield data
    finally:
        # Remove the dataset first: its PolicyDecision rows reference test policies
        # and are removed there via message cascade.
        delete_synthetic_dataset(full_container.session_factory, dataset_name)
        with session_scope(full_container.session_factory) as session:
            policy_ids = list(
                session.scalars(
                    select(Policy.id).where(Policy.policy_key.like(f"{policy_prefix}%"))
                ).all()
            )
            session.execute(delete(OutboxEvent).where(OutboxEvent.dedupe_key.like(f"%{suffix}%")))
            session.execute(
                delete(PlayerEnforcementState).where(
                    PlayerEnforcementState.player_ref == sender_ref
                )
            )
            audit_filter = AuditEvent.entity_id == message_id
            for policy_id in policy_ids:
                audit_filter = audit_filter | (AuditEvent.entity_id == policy_id)
            session.execute(delete(AuditEvent).where(audit_filter))
            if policy_ids:
                session.execute(
                    delete(PolicyVersion).where(PolicyVersion.policy_id.in_(policy_ids))
                )
                session.execute(delete(Policy).where(Policy.id.in_(policy_ids)))
