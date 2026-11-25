from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from claro.data_access.models import (
    AuditEvent,
    CaseEvent,
    Dataset,
    DetectionRule,
    Message,
    ModerationCase,
    Policy,
    PolicyDecision,
    ProcessingEvent,
    RiskFinding,
)
from claro.domain.enums import (
    CaseStatus,
    DecisionAction,
    MessageStatus,
    ProcessingStage,
    ProcessingStatus,
    RiskCategory,
    RuleStatus,
    RuleType,
)

DATASET_NAME = "phase-01-synthetic-v1"
DATASET_SEED = 20261124


def _stable_id(label: str) -> Any:
    return uuid5(NAMESPACE_URL, f"claro:{DATASET_NAME}:{label}")


def seed_synthetic_data(session_factory: sessionmaker[Session]) -> dict[str, Any]:
    with session_factory() as session:
        existing = session.scalar(select(Dataset).where(Dataset.name == DATASET_NAME))
        if existing:
            message_count = session.scalar(
                select(func.count()).select_from(Message).where(Message.dataset_id == existing.id)
            )
            return {"created": False, "dataset": DATASET_NAME, "messages": message_count}

        dataset = Dataset(
            id=_stable_id("dataset"),
            name=DATASET_NAME,
            seed=DATASET_SEED,
            generation_params={
                "message_count": 3,
                "template_version": 1,
                "randomized": False,
                "notice": "All records are synthetic and generated for local verification.",
            },
            is_synthetic=True,
        )
        rule = DetectionRule(
            id=_stable_id("rule"),
            rule_key="synthetic-fraud-keyword",
            version=1,
            rule_type=RuleType.KEYWORD.value,
            definition={"keywords": ["领取游戏金币"], "case_sensitive": False},
            status=RuleStatus.ACTIVE.value,
        )
        policy = Policy(
            id=_stable_id("policy"),
            policy_key="synthetic-default-policy",
            version=1,
            status=RuleStatus.ACTIVE.value,
            definition={
                "review_threshold": 0.8,
                "allow_threshold": 0.2,
                "actions": {"high": "review", "low": "allow"},
            },
        )
        session.add_all([dataset, rule, policy])
        session.flush()

        templates = [
            ("Synthetic: 点击链接领取游戏金币", True),
            ("Synthetic: 免费代充，限时优惠", False),
            ("Synthetic: 公会战今晚八点开始", False),
        ]
        base_time = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
        for index, (content, flagged) in enumerate(templates, start=1):
            message_id = _stable_id(f"message-{index}")
            trace_id = _stable_id(f"trace-{index}").hex
            occurred_at = base_time + timedelta(minutes=index)
            message = Message(
                id=message_id,
                dataset_id=dataset.id,
                external_message_id=f"synthetic-{index:04d}",
                sender_ref=f"synthetic-player-{index}",
                server_ref="synthetic-server-1",
                channel="world",
                content=content,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                language="zh-CN",
                status=MessageStatus.DECIDED.value,
                occurred_at=occurred_at,
                ingested_at=occurred_at,
                is_synthetic=True,
            )
            session.add(message)
            session.add_all(
                [
                    ProcessingEvent(
                        id=_stable_id(f"ingestion-{index}"),
                        message_id=message_id,
                        trace_id=trace_id,
                        sequence=1,
                        stage=ProcessingStage.INGESTION.value,
                        status=ProcessingStatus.SUCCEEDED.value,
                        started_at=occurred_at,
                        finished_at=occurred_at,
                        details={"source": "synthetic-seed"},
                    ),
                    ProcessingEvent(
                        id=_stable_id(f"detection-{index}"),
                        message_id=message_id,
                        trace_id=trace_id,
                        sequence=2,
                        stage=ProcessingStage.DETECTION.value,
                        status=ProcessingStatus.SUCCEEDED.value,
                        started_at=occurred_at,
                        finished_at=occurred_at,
                        details={"synthetic": True},
                    ),
                    ProcessingEvent(
                        id=_stable_id(f"policy-{index}"),
                        message_id=message_id,
                        trace_id=trace_id,
                        sequence=3,
                        stage=ProcessingStage.POLICY.value,
                        status=ProcessingStatus.SUCCEEDED.value,
                        started_at=occurred_at,
                        finished_at=occurred_at,
                        details={"synthetic": True},
                    ),
                ]
            )
            score = Decimal("0.9200") if flagged else Decimal("0.0500")
            if flagged:
                session.add(
                    RiskFinding(
                        id=_stable_id(f"finding-{index}"),
                        message_id=message_id,
                        rule_id=rule.id,
                        detector="synthetic-keyword",
                        detector_version="1.0.0",
                        category=RiskCategory.FRAUD.value,
                        score=score,
                        confidence=Decimal("0.9900"),
                        evidence={"matched_text": "领取游戏金币", "synthetic": True},
                    )
                )
            action = DecisionAction.REVIEW if flagged else DecisionAction.ALLOW
            decision = PolicyDecision(
                id=_stable_id(f"decision-{index}"),
                message_id=message_id,
                policy_id=policy.id,
                action=action.value,
                risk_score=score,
                reason_codes=["synthetic_high_risk"] if flagged else ["synthetic_low_risk"],
                decided_at=occurred_at,
            )
            session.add(decision)
            if flagged and index == 1:
                case = ModerationCase(
                    id=_stable_id("case-1"),
                    message_id=message_id,
                    status=CaseStatus.OPEN.value,
                    priority=1,
                    opened_at=occurred_at,
                )
                session.add(case)
                session.add(
                    CaseEvent(
                        id=_stable_id("case-event-1"),
                        case_id=case.id,
                        event_type="case_opened",
                        actor_type="system",
                        actor_ref="synthetic-seed",
                        to_status=CaseStatus.OPEN.value,
                        note="Synthetic case created for Phase 01 verification.",
                    )
                )

        session.add(
            AuditEvent(
                id=_stable_id("audit-dataset"),
                entity_type="dataset",
                entity_id=dataset.id,
                action="synthetic_seed_created",
                actor_type="system",
                actor_ref="synthetic-seed",
                details={"seed": DATASET_SEED, "synthetic": True},
            )
        )
        session.commit()
        return {"created": True, "dataset": DATASET_NAME, "messages": len(templates)}
