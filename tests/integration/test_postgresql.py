from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import DateTime, Numeric, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from claro.bootstrap import AppContainer
from claro.config.settings import PROJECT_ROOT
from claro.data_access.models import Dataset, Message, PolicyDecision
from claro.data_access.seed import DATASET_NAME, seed_synthetic_data


@pytest.mark.integration
def test_postgresql_connection_and_core_schema(full_container: AppContainer) -> None:
    assert full_container.engine.dialect.name == "postgresql"
    with full_container.engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
    table_names = set(inspect(full_container.engine).get_table_names())
    assert {
        "dataset",
        "message",
        "processing_event",
        "detection_rule",
        "risk_finding",
        "policy",
        "policy_decision",
        "moderation_case",
        "case_event",
        "enforcement_action",
        "audit_event",
    }.issubset(table_names)

    inspector = inspect(full_container.engine)
    message_columns = {
        column["name"]: column["type"] for column in inspector.get_columns("message")
    }
    occurred_at_type = message_columns["occurred_at"]
    assert isinstance(occurred_at_type, DateTime)
    assert occurred_at_type.timezone

    decision_columns = {
        column["name"]: column["type"] for column in inspector.get_columns("policy_decision")
    }
    risk_score_type = decision_columns["risk_score"]
    assert isinstance(risk_score_type, Numeric)
    assert risk_score_type.precision == 5
    assert risk_score_type.scale == 4

    first_seed = seed_synthetic_data(full_container.session_factory)
    second_seed = seed_synthetic_data(full_container.session_factory)
    assert first_seed["messages"] == 3
    assert second_seed == {**first_seed, "created": False}

    with full_container.session_factory() as session:
        # Scope the fixture to the dataset this test seeded. Selecting any
        # synthetic message would reach into the shared demonstration
        # dataset, and the timestamp rewrite below must not survive the test:
        # a permanently moved message would silently change every analytics
        # window that follows.
        seed_dataset = session.scalar(select(Dataset).where(Dataset.name == DATASET_NAME))
        assert seed_dataset is not None
        message = session.scalar(
            select(Message)
            .where(Message.dataset_id == seed_dataset.id)
            .order_by(Message.occurred_at, Message.external_message_id)
        )
        assert message is not None
        decision = session.scalar(
            select(PolicyDecision).where(PolicyDecision.message_id == message.id)
        )
        assert message.occurred_at.tzinfo is not None
        assert message.occurred_at.utcoffset() == timedelta(0)
        assert decision is not None
        assert isinstance(decision.risk_score, Decimal)
        message_id = message.id
        original_occurred_at = message.occurred_at

    source_time = datetime(2026, 11, 24, 12, 30, tzinfo=timezone(timedelta(hours=8)))
    expected_utc = source_time.astimezone(UTC)
    try:
        with full_container.engine.begin() as connection:
            connection.execute(text("SET LOCAL TIME ZONE 'Asia/Shanghai'"))
            assert connection.execute(text("SHOW TIME ZONE")).scalar_one() == "Asia/Shanghai"
            connection.execute(
                update(Message).where(Message.id == message_id).values(occurred_at=source_time)
            )
            stored_utc = connection.execute(
                text("SELECT occurred_at AT TIME ZONE 'UTC' FROM message WHERE id = :message_id"),
                {"message_id": message_id},
            ).scalar_one()
            loaded_time = connection.execute(
                select(Message.occurred_at).where(Message.id == message_id)
            ).scalar_one()

        assert stored_utc == expected_utc.replace(tzinfo=None)
        assert loaded_time == expected_utc
        assert loaded_time.tzinfo is not None
        assert loaded_time.utcoffset() == timedelta(0)
    finally:
        # Restore the original timestamp. Leaving it rewritten would move the
        # message out of every analytics window that includes it, so the
        # reported message counts would drift on each test run.
        with full_container.engine.begin() as connection:
            connection.execute(
                update(Message)
                .where(Message.id == message_id)
                .values(occurred_at=original_occurred_at)
            )

    with full_container.session_factory() as session:
        restored = session.get(Message, message_id)
        assert restored is not None
        assert restored.occurred_at == original_occurred_at

    with full_container.session_factory() as session:
        message = session.get(Message, message_id)
        assert message is not None
        decision = session.scalar(
            select(PolicyDecision).where(PolicyDecision.message_id == message.id)
        )
        assert decision is not None
        invalid_decision = PolicyDecision(
            id=uuid4(),
            message_id=message.id,
            policy_id=decision.policy_id,
            action="allow",
            risk_score=Decimal("1.5000"),
            reason_codes=["synthetic_invalid_score"],
            decided_at=datetime.now(UTC),
        )
        session.add(invalid_decision)
        with pytest.raises(IntegrityError):
            session.flush()

    alembic_config = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    command.check(alembic_config)
