from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.orm import Session, sessionmaker

from claro.data_access.database import session_scope
from claro.data_access.models import (
    Alliance,
    AuditEvent,
    CaseEvent,
    Dataset,
    DetectionRule,
    EnforcementAction,
    InboxEvent,
    Message,
    MessageLabel,
    ModerationCase,
    ModerationRecord,
    Player,
    Policy,
    PolicyDecision,
    PolicyRule,
    ProcessingEvent,
    RiskEvent,
    RiskFinding,
    Server,
)
from claro.data_generation.generator import GeneratedDataset
from claro.domain.enums import (
    CaseStatus,
    DecisionAction,
    EnforcementStatus,
    MessageStatus,
    ProcessingStage,
    ProcessingStatus,
)


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _derived_id(kind: str, source: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"claro:phase-02:{kind}:{source}")


def _insert_batches(
    session: Session,
    model: type[Any],
    rows: Iterable[dict[str, Any]],
    batch_size: int,
) -> None:
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= batch_size:
            session.execute(insert(model), batch)
            batch.clear()
    if batch:
        session.execute(insert(model), batch)


def _dataset_counts(session: Session, dataset_id: Any) -> dict[str, int]:
    message_ids = select(Message.id).where(Message.dataset_id == dataset_id)
    counts = {
        "servers": session.scalar(
            select(func.count()).select_from(Server).where(Server.dataset_id == dataset_id)
        ),
        "alliances": session.scalar(
            select(func.count()).select_from(Alliance).where(Alliance.dataset_id == dataset_id)
        ),
        "players": session.scalar(
            select(func.count()).select_from(Player).where(Player.dataset_id == dataset_id)
        ),
        "messages": session.scalar(
            select(func.count()).select_from(Message).where(Message.dataset_id == dataset_id)
        ),
        "message_labels": session.scalar(
            select(func.count())
            .select_from(MessageLabel)
            .where(MessageLabel.dataset_id == dataset_id)
        ),
        "processing_events": session.scalar(
            select(func.count())
            .select_from(ProcessingEvent)
            .where(ProcessingEvent.message_id.in_(message_ids))
        ),
        "risk_findings": session.scalar(
            select(func.count())
            .select_from(RiskFinding)
            .where(RiskFinding.message_id.in_(message_ids))
        ),
        "risk_events": session.scalar(
            select(func.count()).select_from(RiskEvent).where(RiskEvent.dataset_id == dataset_id)
        ),
        "policy_decisions": session.scalar(
            select(func.count())
            .select_from(PolicyDecision)
            .where(PolicyDecision.message_id.in_(message_ids))
        ),
        "moderation_cases": session.scalar(
            select(func.count())
            .select_from(ModerationCase)
            .where(ModerationCase.message_id.in_(message_ids))
        ),
        "moderation_records": session.scalar(
            select(func.count())
            .select_from(ModerationRecord)
            .where(ModerationRecord.dataset_id == dataset_id)
        ),
        "policies": session.scalar(
            select(func.count()).select_from(Policy).where(Policy.dataset_id == dataset_id)
        ),
        "policy_rules": session.scalar(
            select(func.count()).select_from(PolicyRule).where(PolicyRule.dataset_id == dataset_id)
        ),
        "enforcement_actions": session.scalar(
            select(func.count())
            .select_from(EnforcementAction)
            .where(
                EnforcementAction.decision_id.in_(
                    select(PolicyDecision.id).where(PolicyDecision.message_id.in_(message_ids))
                )
            )
        ),
    }
    return {name: int(count or 0) for name, count in counts.items()}


def _delete_dataset(session: Session, dataset_id: Any) -> None:
    message_ids = select(Message.id).where(Message.dataset_id == dataset_id)
    case_ids = select(ModerationCase.id).where(ModerationCase.message_id.in_(message_ids))
    decision_ids = select(PolicyDecision.id).where(PolicyDecision.message_id.in_(message_ids))

    session.execute(
        delete(EnforcementAction).where(
            or_(
                EnforcementAction.decision_id.in_(decision_ids),
                EnforcementAction.case_id.in_(case_ids),
            )
        )
    )
    session.execute(delete(CaseEvent).where(CaseEvent.case_id.in_(case_ids)))
    session.execute(delete(ModerationRecord).where(ModerationRecord.dataset_id == dataset_id))
    session.execute(delete(ModerationCase).where(ModerationCase.message_id.in_(message_ids)))
    session.execute(delete(PolicyDecision).where(PolicyDecision.message_id.in_(message_ids)))
    session.execute(delete(RiskEvent).where(RiskEvent.dataset_id == dataset_id))
    session.execute(delete(RiskFinding).where(RiskFinding.message_id.in_(message_ids)))
    session.execute(delete(MessageLabel).where(MessageLabel.dataset_id == dataset_id))
    session.execute(delete(ProcessingEvent).where(ProcessingEvent.message_id.in_(message_ids)))
    session.execute(delete(InboxEvent).where(InboxEvent.event_id.in_(message_ids)))
    session.execute(delete(Message).where(Message.dataset_id == dataset_id))
    session.execute(delete(PolicyRule).where(PolicyRule.dataset_id == dataset_id))
    session.execute(delete(Player).where(Player.dataset_id == dataset_id))
    session.execute(delete(Alliance).where(Alliance.dataset_id == dataset_id))
    session.execute(delete(Server).where(Server.dataset_id == dataset_id))
    session.execute(delete(DetectionRule).where(DetectionRule.dataset_id == dataset_id))
    session.execute(delete(Policy).where(Policy.dataset_id == dataset_id))
    session.execute(
        delete(AuditEvent).where(
            AuditEvent.entity_type == "dataset", AuditEvent.entity_id == dataset_id
        )
    )
    session.execute(delete(Dataset).where(Dataset.id == dataset_id))
    session.flush()


def delete_synthetic_dataset(
    session_factory: sessionmaker[Session], dataset_name: str
) -> dict[str, Any]:
    with session_scope(session_factory) as session:
        dataset = session.scalar(select(Dataset).where(Dataset.name == dataset_name))
        if dataset is None:
            return {"deleted": False, "dataset": dataset_name}
        is_phase_02 = (
            dataset.name.startswith("phase-02-synthetic-")
            or (dataset.generation_params or {}).get("template_version") == 2
        )
        if not dataset.is_synthetic or not is_phase_02:
            raise ValueError("only Phase 02 synthetic datasets can be deleted with this command")
        _delete_dataset(session, dataset.id)
        return {"deleted": True, "dataset": dataset_name}


def _server_rows(generated: GeneratedDataset) -> Iterator[dict[str, Any]]:
    for item in generated.servers:
        yield {
            "id": item.id,
            "dataset_id": item.dataset_id,
            "server_ref": item.server_ref,
            "name": item.name,
            "region": item.region,
            "is_synthetic": item.is_synthetic,
        }


def _alliance_rows(generated: GeneratedDataset) -> Iterator[dict[str, Any]]:
    for item in generated.alliances:
        yield {
            "id": item.id,
            "dataset_id": item.dataset_id,
            "server_id": item.server_id,
            "server_ref": item.server_ref,
            "alliance_ref": item.alliance_ref,
            "name": item.name,
            "is_synthetic": item.is_synthetic,
        }


def _player_rows(generated: GeneratedDataset) -> Iterator[dict[str, Any]]:
    for item in generated.players:
        yield {
            "id": item.id,
            "dataset_id": item.dataset_id,
            "player_ref": item.player_ref,
            "display_name": item.display_name,
            "server_id": item.server_id,
            "server_ref": item.server_ref,
            "alliance_id": item.alliance_id,
            "alliance_ref": item.alliance_ref,
            "behavior_profile": {
                "profile": item.behavior_profile,
                "risk_propensity": item.risk_propensity,
                "activity_factor": item.activity_factor,
                "chattiness": item.chattiness,
                "synthetic": True,
            },
            "risk_propensity": _decimal(item.risk_propensity),
            "activity_factor": _decimal(item.activity_factor),
            "chattiness": _decimal(item.chattiness),
            "account_created_at": item.account_created_at,
            "is_synthetic": item.is_synthetic,
        }


def _policy_rows(generated: GeneratedDataset) -> Iterator[dict[str, Any]]:
    for item in generated.policies:
        yield {
            "id": item.id,
            "dataset_id": item.dataset_id,
            "policy_key": item.policy_key,
            "version": item.version,
            "status": item.status,
            "definition": item.definition,
            "effective_from": item.effective_from,
            "is_synthetic": item.is_synthetic,
        }


def _detection_rule_rows(generated: GeneratedDataset) -> Iterator[dict[str, Any]]:
    for item in generated.policy_rules:
        yield {
            "id": item.detection_rule_id,
            "dataset_id": item.dataset_id,
            "rule_key": item.rule_key,
            "version": 1,
            "rule_type": item.rule_type,
            "definition": item.definition,
            "status": item.status,
            "effective_from": item.effective_from,
            "is_synthetic": item.is_synthetic,
        }


def _policy_rule_rows(generated: GeneratedDataset) -> Iterator[dict[str, Any]]:
    for item in generated.policy_rules:
        yield {
            "id": item.id,
            "dataset_id": item.dataset_id,
            "policy_id": item.policy_id,
            "detection_rule_id": item.detection_rule_id,
            "rule_key": item.rule_key,
            "version": 1,
            "category": item.category,
            "rule_type": item.rule_type,
            "priority": item.priority,
            "threshold": _decimal(item.threshold),
            "action": item.action,
            "definition": item.definition,
            "status": item.status,
            "effective_from": item.effective_from,
            "is_synthetic": item.is_synthetic,
        }


def _message_rows(generated: GeneratedDataset) -> Iterator[dict[str, Any]]:
    for item in generated.messages:
        yield {
            "id": item.id,
            "dataset_id": item.dataset_id,
            "player_id": item.player_id,
            "server_id": item.server_id,
            "alliance_id": item.alliance_id,
            "external_message_id": item.external_message_id,
            "sender_ref": item.player_ref,
            "server_ref": item.server_ref,
            "channel": item.channel,
            "content": item.content,
            "content_hash": item.content_hash,
            "language": item.language,
            "status": MessageStatus.DECIDED.value,
            "occurred_at": item.occurred_at,
            "ingested_at": item.occurred_at,
            "is_synthetic": item.is_synthetic,
        }


def _label_rows(generated: GeneratedDataset) -> Iterator[dict[str, Any]]:
    for item in generated.labels:
        yield {
            "id": item.id,
            "dataset_id": item.dataset_id,
            "message_id": item.message_id,
            "label": item.label,
            "risk_category": item.risk_category,
            "split": item.split,
            "annotator_type": item.annotator_type,
            "annotator_ref": item.annotator_ref,
            "confidence": _decimal(item.confidence),
            "rationale": item.rationale,
            "labeled_at": item.labeled_at,
            "is_synthetic": item.is_synthetic,
        }


def _risk_finding_rows(generated: GeneratedDataset) -> Iterator[dict[str, Any]]:
    for item in generated.risk_events:
        yield {
            "id": item.id,
            "message_id": item.message_id,
            "rule_id": item.rule_id,
            "detector": str(item.details["detector"]),
            "detector_version": str(item.details["detector_version"]),
            "category": item.category,
            "score": _decimal(item.risk_score),
            "confidence": _decimal(item.confidence),
            "evidence": item.details,
            "created_at": item.occurred_at,
        }


def _risk_event_rows(generated: GeneratedDataset) -> Iterator[dict[str, Any]]:
    for item in generated.risk_events:
        yield {
            "id": item.id,
            "dataset_id": item.dataset_id,
            "message_id": item.message_id,
            "rule_id": item.rule_id,
            "category": item.category,
            "event_type": item.event_type,
            "risk_score": _decimal(item.risk_score),
            "confidence": _decimal(item.confidence),
            "severity": item.severity,
            "occurred_at": item.occurred_at,
            "details": item.details,
            "is_synthetic": item.is_synthetic,
        }


def _policy_decision_rows(generated: GeneratedDataset) -> Iterator[dict[str, Any]]:
    for item in generated.policy_decisions:
        yield {
            "id": item.id,
            "message_id": item.message_id,
            "policy_id": item.policy_id,
            "action": item.action,
            "risk_score": _decimal(item.risk_score),
            "reason_codes": list(item.reason_codes),
            "decided_at": item.decided_at,
            "is_synthetic": item.is_synthetic,
        }


def _processing_event_rows(generated: GeneratedDataset) -> Iterator[dict[str, Any]]:
    moderated_ids = {item.message_id for item in generated.moderation_records}
    stages = (
        (ProcessingStage.INGESTION, 0, 1),
        (ProcessingStage.PREPROCESSING, 1, 2),
        (ProcessingStage.DETECTION, 2, 3),
        (ProcessingStage.POLICY, 120, 121),
    )
    for message in generated.messages:
        for sequence, (stage, start_seconds, finish_seconds) in enumerate(stages, start=1):
            yield {
                "id": _derived_id("processing", f"{message.trace_id}:{sequence}"),
                "message_id": message.id,
                "trace_id": message.trace_id,
                "sequence": sequence,
                "stage": stage.value,
                "status": ProcessingStatus.SUCCEEDED.value,
                "started_at": message.occurred_at + timedelta(seconds=start_seconds),
                "finished_at": message.occurred_at + timedelta(seconds=finish_seconds),
                "details": {"synthetic": True, "dataset_id": str(message.dataset_id)},
            }
        yield {
            "id": _derived_id("processing", f"{message.trace_id}:5"),
            "message_id": message.id,
            "trace_id": message.trace_id,
            "sequence": 5,
            "stage": ProcessingStage.MODERATION.value,
            "status": (
                ProcessingStatus.SUCCEEDED.value
                if message.id in moderated_ids
                else ProcessingStatus.SKIPPED.value
            ),
            "started_at": message.occurred_at + timedelta(minutes=8),
            "finished_at": message.occurred_at + timedelta(minutes=8, seconds=1),
            "details": {"synthetic": True, "dataset_id": str(message.dataset_id)},
        }


def _moderation_rows(
    generated: GeneratedDataset,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    cases: list[dict[str, Any]] = []
    case_events: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    case_by_message: dict[Any, Any] = {}
    for item in generated.moderation_records:
        case_id = None
        if item.action in {DecisionAction.REVIEW.value, DecisionAction.BLOCK.value}:
            case_id = _derived_id("moderation-case", str(item.message_id))
            case_by_message[item.message_id] = case_id
            cases.append(
                {
                    "id": case_id,
                    "message_id": item.message_id,
                    "status": CaseStatus.RESOLVED.value,
                    "priority": 1 if item.action == DecisionAction.BLOCK.value else 2,
                    "assignee_ref": item.actor_ref if item.actor_type == "human" else None,
                    "resolution": item.action,
                    "opened_at": item.occurred_at,
                    "closed_at": item.occurred_at + timedelta(minutes=2),
                    "is_synthetic": True,
                }
            )
            case_events.append(
                {
                    "id": _derived_id("case-event", str(item.message_id)),
                    "case_id": case_id,
                    "event_type": "synthetic_moderation_completed",
                    "actor_type": item.actor_type,
                    "actor_ref": item.actor_ref,
                    "from_status": CaseStatus.OPEN.value,
                    "to_status": CaseStatus.RESOLVED.value,
                    "note": item.note,
                    "created_at": item.occurred_at,
                }
            )
        records.append(
            {
                "id": item.id,
                "dataset_id": item.dataset_id,
                "message_id": item.message_id,
                "case_id": case_id,
                "idempotency_key": f"synthetic-moderation:{item.id}",
                "action": item.action,
                "actor_type": item.actor_type,
                "actor_ref": item.actor_ref,
                "risk_score": _decimal(item.risk_score),
                "reason_codes": list(item.reason_codes),
                "note": item.note,
                "occurred_at": item.occurred_at,
                "is_synthetic": item.is_synthetic,
            }
        )
    return cases, case_events, records


def _enforcement_rows(
    generated: GeneratedDataset,
) -> Iterator[dict[str, Any]]:
    decision_by_message = {item.message_id: item for item in generated.policy_decisions}
    player_by_message = {item.id: item.player_ref for item in generated.messages}
    case_by_message = {
        item.message_id: _derived_id("moderation-case", str(item.message_id))
        for item in generated.moderation_records
        if item.action == DecisionAction.BLOCK.value
    }
    for item in generated.moderation_records:
        if item.action != DecisionAction.BLOCK.value:
            continue
        decision = decision_by_message[item.message_id]
        yield {
            "id": _derived_id("enforcement", str(item.message_id)),
            "decision_id": decision.id,
            "case_id": case_by_message[item.message_id],
            "idempotency_key": f"synthetic-enforcement:{item.message_id}",
            "action_type": "message_block",
            "target_ref": player_by_message[item.message_id],
            "status": EnforcementStatus.EXECUTED.value,
            "executed_at": item.occurred_at,
            "metadata": {"synthetic": True, "source": "phase-02-generator"},
            "is_synthetic": True,
        }


def load_generated_dataset(
    session_factory: sessionmaker[Session],
    generated: GeneratedDataset,
    batch_size: int = 1_000,
    clean: bool = False,
) -> dict[str, Any]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    fingerprint = generated.fingerprint()
    generation_params = {
        **generated.dataset.generation_params,
        "fingerprint": fingerprint,
        "template_version": 2,
    }
    with session_scope(session_factory) as session:
        existing = session.scalar(select(Dataset).where(Dataset.name == generated.dataset.name))
        if existing is not None:
            existing_fingerprint = (existing.generation_params or {}).get("fingerprint")
            if not clean and existing_fingerprint not in {None, fingerprint}:
                raise ValueError(
                    "dataset name already exists with a different fingerprint; "
                    "use --clean to replace it"
                )
            if not clean:
                return {
                    "created": False,
                    "dataset": existing.name,
                    "fingerprint": fingerprint,
                    "counts": _dataset_counts(session, existing.id),
                }
            _delete_dataset(session, existing.id)

        session.add(
            Dataset(
                id=generated.dataset.id,
                name=generated.dataset.name,
                seed=generated.dataset.seed,
                generation_params=generation_params,
                is_synthetic=True,
            )
        )
        session.flush()
        _insert_batches(session, Server, _server_rows(generated), batch_size)
        _insert_batches(session, Alliance, _alliance_rows(generated), batch_size)
        _insert_batches(session, Player, _player_rows(generated), batch_size)
        _insert_batches(session, Policy, _policy_rows(generated), batch_size)
        _insert_batches(session, DetectionRule, _detection_rule_rows(generated), batch_size)
        _insert_batches(session, PolicyRule, _policy_rule_rows(generated), batch_size)
        _insert_batches(session, Message, _message_rows(generated), batch_size)
        _insert_batches(session, MessageLabel, _label_rows(generated), batch_size)
        _insert_batches(session, RiskFinding, _risk_finding_rows(generated), batch_size)
        _insert_batches(session, RiskEvent, _risk_event_rows(generated), batch_size)
        _insert_batches(session, PolicyDecision, _policy_decision_rows(generated), batch_size)
        _insert_batches(session, ProcessingEvent, _processing_event_rows(generated), batch_size)

        cases, case_events, moderation_records = _moderation_rows(generated)
        _insert_batches(session, ModerationCase, cases, batch_size)
        _insert_batches(session, CaseEvent, case_events, batch_size)
        _insert_batches(session, ModerationRecord, moderation_records, batch_size)
        _insert_batches(session, EnforcementAction, _enforcement_rows(generated), batch_size)
        session.add(
            AuditEvent(
                id=_derived_id("dataset-audit", str(generated.dataset.id)),
                entity_type="dataset",
                entity_id=generated.dataset.id,
                action="synthetic_dataset_loaded",
                actor_type="system",
                actor_ref="claro-phase-02",
                details={
                    "synthetic": True,
                    "seed": generated.spec.seed,
                    "fingerprint": fingerprint,
                    "counts": generated.summary()["counts"],
                },
            )
        )
        session.flush()
        return {
            "created": True,
            "dataset": generated.dataset.name,
            "fingerprint": fingerprint,
            "counts": _dataset_counts(session, generated.dataset.id),
        }


def check_dataset_quality(
    session_factory: sessionmaker[Session], dataset_name: str
) -> dict[str, Any]:
    with session_factory() as session:
        dataset = session.scalar(select(Dataset).where(Dataset.name == dataset_name))
        if dataset is None:
            raise ValueError(f"dataset not found: {dataset_name}")
        message_ids = select(Message.id).where(Message.dataset_id == dataset.id)
        counts = _dataset_counts(session, dataset.id)
        missing_labels = session.scalar(
            select(func.count())
            .select_from(Message)
            .outerjoin(MessageLabel, MessageLabel.message_id == Message.id)
            .where(Message.dataset_id == dataset.id, MessageLabel.id.is_(None))
        )
        duplicate_messages = session.scalar(
            select(func.count()).select_from(
                select(Message.external_message_id)
                .where(Message.dataset_id == dataset.id)
                .group_by(Message.external_message_id)
                .having(func.count() > 1)
                .subquery()
            )
        )
        split_leakage = session.scalar(
            select(func.count()).select_from(
                select(Message.player_id)
                .join(MessageLabel, MessageLabel.message_id == Message.id)
                .where(Message.dataset_id == dataset.id)
                .group_by(Message.player_id)
                .having(func.count(func.distinct(MessageLabel.split)) > 1)
                .subquery()
            )
        )
        orphan_messages = session.scalar(
            select(func.count())
            .select_from(Message)
            .outerjoin(Player, Player.id == Message.player_id)
            .outerjoin(Server, Server.id == Message.server_id)
            .where(
                Message.dataset_id == dataset.id,
                or_(Player.id.is_(None), Server.id.is_(None)),
            )
        )
        non_synthetic = 0
        for model in (
            Server,
            Alliance,
            Player,
            Message,
            MessageLabel,
            RiskEvent,
            ModerationRecord,
            Policy,
            DetectionRule,
            PolicyRule,
            PolicyDecision,
        ):
            dataset_column = model.dataset_id
            non_synthetic += int(
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(dataset_column == dataset.id, model.is_synthetic.is_(False))
                )
                or 0
            )
        decision_ids = select(PolicyDecision.id).where(PolicyDecision.message_id.in_(message_ids))
        non_synthetic += int(
            session.scalar(
                select(func.count())
                .select_from(ModerationCase)
                .where(
                    ModerationCase.message_id.in_(message_ids),
                    ModerationCase.is_synthetic.is_(False),
                )
            )
            or 0
        )
        non_synthetic += int(
            session.scalar(
                select(func.count())
                .select_from(EnforcementAction)
                .where(
                    EnforcementAction.decision_id.in_(decision_ids),
                    EnforcementAction.is_synthetic.is_(False),
                )
            )
            or 0
        )
        label_distribution = {
            str(label): int(count)
            for label, count in session.execute(
                select(MessageLabel.label, func.count())
                .where(MessageLabel.dataset_id == dataset.id)
                .group_by(MessageLabel.label)
            )
        }
        expected = dataset.generation_params or {}
        expected_messages = int(expected.get("messages", counts["messages"]))
        checks = {
            "message_count_matches": counts["messages"] == expected_messages,
            "every_message_has_one_label": counts["message_labels"] == counts["messages"],
            "every_message_has_one_decision": counts["policy_decisions"] == counts["messages"],
            "no_duplicate_external_ids": int(duplicate_messages or 0) == 0,
            "no_missing_labels": int(missing_labels or 0) == 0,
            "no_orphan_player_server_links": int(orphan_messages or 0) == 0,
            "no_player_split_leakage": int(split_leakage or 0) == 0,
            "all_records_marked_synthetic": non_synthetic == 0,
        }
        return {
            "dataset": dataset_name,
            "passed": all(checks.values()),
            "checks": checks,
            "counts": counts,
            "label_distribution": label_distribution,
            "fingerprint": expected.get("fingerprint"),
        }
