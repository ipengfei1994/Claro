from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from claro.data_access.database import session_scope
from claro.data_access.models import (
    AuditEvent,
    CaseEvent,
    EnforcementAction,
    GovernanceFeedback,
    Message,
    MessageLabel,
    ModerationCase,
    ModerationReview,
    OutboxEvent,
    PlayerEnforcementState,
    PolicyDecision,
    PolicyEvaluation,
    RiskResult,
)
from claro.domain.enums import (
    CaseStatus,
    DecisionAction,
    EnforcementStatus,
    FeedbackType,
    GovernanceDecisionStatus,
    MessageDisplayStatus,
    ModerationAction,
    OutboxStatus,
    RiskSeverity,
)
from claro.governance.enforcement import (
    EnforcementValidationError,
    plan_enforcement,
    validate_target_ref,
)
from claro.governance.moderation import (
    ModerationConflictError,
    ModerationWorkflowError,
    build_review_outcome,
    validate_claim,
)
from claro.governance.policy import PolicyContext, PolicyEvaluationOutcome

logger = structlog.get_logger(__name__)


class GovernanceNotFoundError(LookupError):
    pass


class GovernanceValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OutboxDraft:
    event_type: str
    topic: str
    payload: dict[str, Any]
    dedupe_key: str
    headers: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CaseDraft:
    status: str
    priority: int
    required_second_review: bool
    due_at: datetime | None
    risk_snapshot: dict[str, Any]
    final_category: str | None = None
    final_level: str | None = None
    final_action: str | None = None


@dataclass(frozen=True, slots=True)
class GovernanceTopics:
    evaluated: str = "game.governance.evaluated.v1"
    decision: str = "game.governance.decisions.v1"
    moderation: str = "game.governance.moderation.v1"
    enforcement: str = "game.governance.enforcement.v1"
    feedback: str = "game.governance.feedback.v1"


class GovernanceRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        topics: GovernanceTopics | None = None,
    ) -> None:
        self._sessions = session_factory
        self._topics = topics or GovernanceTopics()

    @property
    def topics(self) -> GovernanceTopics:
        return self._topics

    # ------------------------------------------------------------------
    # Message and evaluation
    # ------------------------------------------------------------------
    def message_context(self, message_id: UUID, *, rate_count: int = 0) -> dict[str, Any]:
        with session_scope(self._sessions) as session:
            message = session.get(Message, message_id)
            if message is None:
                raise GovernanceNotFoundError(f"message not found: {message_id}")
            risk = session.scalar(select(RiskResult).where(RiskResult.message_id == message_id))
            if risk is None:
                raise GovernanceValidationError(
                    "message has no stored risk result; run risk detection before evaluation"
                )
            categories = [item for item in (risk.categories or []) if item.get("db_category")]
            scores = {str(item["db_category"]): float(item.get("score", 0)) for item in categories}
            label = session.scalar(
                select(MessageLabel).where(MessageLabel.message_id == message_id)
            )
            context = PolicyContext(
                message_id=message.id,
                content=message.content,
                content_hash=message.content_hash,
                channel=message.channel,
                language=message.language,
                sender_ref=message.sender_ref,
                server_ref=message.server_ref,
                alliance_id=str(message.alliance_id) if message.alliance_id else None,
                risk_score=float(risk.risk_score),
                risk_level=str(risk.risk_level),
                confidence=float(risk.confidence),
                categories=tuple(scores),
                category_scores=scores,
                rate_count=rate_count,
                occurred_at=message.occurred_at,
            )
            return {
                "message": _message_dict(message),
                "risk": _risk_dict(risk, categories),
                "label": (
                    {
                        "label": label.label,
                        "risk_category": label.risk_category,
                        "split": label.split,
                    }
                    if label is not None
                    else None
                ),
                "findings": list((risk.evidence or {}).get("findings", [])),
                "policy_context": context,
            }

    def message(self, message_id: UUID) -> dict[str, Any] | None:
        with session_scope(self._sessions) as session:
            row = session.get(Message, message_id)
            return _message_dict(row) if row is not None else None

    def sender_message_rate(
        self, sender_ref: str, *, window_seconds: int, now: datetime | None = None
    ) -> int:
        """Count messages a sender produced within a sliding time window.

        PostgreSQL is the authoritative source for behavioural counters; Redis
        only caches the result. This keeps rate-limit evaluation idempotent when
        the same message is evaluated more than once.
        """
        if not isinstance(sender_ref, str) or not sender_ref.strip():
            raise GovernanceValidationError("sender_ref must be a non-empty string")
        if window_seconds < 1:
            raise GovernanceValidationError("window_seconds must be positive")
        moment = now or datetime.now(UTC)
        since = moment - timedelta(seconds=window_seconds)
        with session_scope(self._sessions) as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(Message)
                    .where(
                        Message.sender_ref == sender_ref,
                        Message.occurred_at >= since,
                        Message.occurred_at <= moment,
                    )
                )
                or 0
            )

    def save_evaluation(
        self,
        *,
        context: PolicyContext,
        outcome: PolicyEvaluationOutcome,
        risk_result_id: UUID,
        dataset_id: UUID | None,
        is_synthetic: bool,
    ) -> dict[str, Any]:
        with session_scope(self._sessions) as session:
            existing = session.scalar(
                select(PolicyEvaluation).where(
                    PolicyEvaluation.message_id == context.message_id,
                    PolicyEvaluation.policy_snapshot_hash == outcome.snapshot_hash,
                )
            )
            if existing is not None:
                return {**_evaluation_dict(existing), "created": False}
            row = PolicyEvaluation(
                dataset_id=dataset_id,
                message_id=context.message_id,
                risk_result_id=risk_result_id,
                policy_snapshot_hash=outcome.snapshot_hash,
                risk_score=Decimal(str(context.risk_score)),
                risk_level=context.risk_level,
                input_snapshot={
                    "content": context.content,
                    "channel": context.channel,
                    "language": context.language,
                    "sender_ref": context.sender_ref,
                    "server_ref": context.server_ref,
                    "alliance_id": context.alliance_id,
                    "risk_score": context.risk_score,
                    "risk_level": context.risk_level,
                    "confidence": context.confidence,
                    "categories": list(context.categories),
                    "rate_count": context.rate_count,
                },
                matched_policies=[_match_summary(item) for item in outcome.matched],
                unmatched_policies=[
                    {
                        "policy_key": item.policy_key,
                        "version": item.version,
                        "enabled": item.enabled,
                    }
                    for item in outcome.unmatched
                ],
                matched_conditions=list(outcome.matched_conditions),
                conflicts=list(outcome.conflicts),
                selected_policy_id=(
                    outcome.selected_policy.policy_id if outcome.selected_policy else None
                ),
                selected_policy_version=(
                    outcome.selected_policy.version if outcome.selected_policy else None
                ),
                suggested_action=outcome.action,
                evaluation_reason=outcome.reason,
                is_synthetic=is_synthetic,
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                existing = session.scalar(
                    select(PolicyEvaluation).where(
                        PolicyEvaluation.message_id == context.message_id,
                        PolicyEvaluation.policy_snapshot_hash == outcome.snapshot_hash,
                    )
                )
                if existing is None:
                    raise
                return {**_evaluation_dict(existing), "created": False}
            session.add(
                AuditEvent(
                    entity_type="policy_evaluation",
                    entity_id=row.id,
                    action="policy.evaluated",
                    actor_type="system",
                    actor_ref="governance-engine",
                    actor_role="system",
                    reason=outcome.reason,
                    after_state=_evaluation_dict(row),
                )
            )
            return {**_evaluation_dict(row), "created": True}

    def get_evaluation(self, evaluation_id: UUID) -> dict[str, Any] | None:
        with session_scope(self._sessions) as session:
            row = session.get(PolicyEvaluation, evaluation_id)
            return _evaluation_dict(row) if row is not None else None

    def latest_evaluation(self, message_id: UUID) -> dict[str, Any] | None:
        with session_scope(self._sessions) as session:
            row = session.scalar(
                select(PolicyEvaluation)
                .where(PolicyEvaluation.message_id == message_id)
                .order_by(PolicyEvaluation.evaluated_at.desc())
                .limit(1)
            )
            return _evaluation_dict(row) if row is not None else None

    def list_evaluations(self, limit: int = 100) -> list[dict[str, Any]]:
        with session_scope(self._sessions) as session:
            rows = session.scalars(
                select(PolicyEvaluation).order_by(PolicyEvaluation.evaluated_at.desc()).limit(limit)
            ).all()
            return [_evaluation_dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Decisions and cases
    # ------------------------------------------------------------------
    def create_decision(
        self,
        *,
        message_id: UUID,
        dataset_id: UUID | None,
        policy_id: UUID,
        action: str,
        risk_score: float,
        risk_level: str,
        confidence: float,
        decision_key: str,
        decision_status: str,
        decision_reason: str,
        requires_review: bool,
        priority: int,
        risk_result_id: UUID | None,
        policy_evaluation_id: UUID | None,
        decided_by: str,
        explanation: dict[str, Any],
        is_synthetic: bool,
        case_draft: CaseDraft | None,
        outbox: OutboxDraft | None,
    ) -> dict[str, Any]:
        with session_scope(self._sessions) as session:
            existing = session.scalar(
                select(PolicyDecision).where(PolicyDecision.decision_key == decision_key)
            )
            if existing is not None:
                return {**_decision_dict(existing), "created": False}
            row = PolicyDecision(
                message_id=message_id,
                dataset_id=dataset_id,
                policy_id=policy_id,
                action=action,
                risk_score=Decimal(str(risk_score)),
                reason_codes=[decision_status, risk_level, action],
                risk_result_id=risk_result_id,
                policy_evaluation_id=policy_evaluation_id,
                decision_key=decision_key,
                decision_status=decision_status,
                decision_reason=decision_reason,
                confidence=Decimal(str(confidence)),
                requires_review=requires_review,
                priority=priority,
                decided_by=decided_by,
                explanation=explanation,
                is_synthetic=is_synthetic,
            )
            session.add(row)
            session.flush()
            case_id: UUID | None = None
            if case_draft is not None:
                case_id = self._create_case(session, row, case_draft)
            _audit(
                session,
                entity_type="policy_decision",
                entity_id=row.id,
                action="decision.recorded",
                actor_ref=decided_by,
                actor_role="system",
                reason=decision_reason,
                after=_decision_dict(row) | {"case_id": str(case_id) if case_id else None},
            )
            if outbox is not None:
                _enqueue(
                    session,
                    replace(
                        outbox,
                        payload={
                            **outbox.payload,
                            "decision_id": str(row.id),
                            "case_id": str(case_id) if case_id else None,
                        },
                    ),
                )
            return {
                **_decision_dict(row),
                "created": True,
                "case_id": str(case_id) if case_id else None,
            }

    def get_decision(self, decision_id: UUID) -> dict[str, Any] | None:
        with session_scope(self._sessions) as session:
            row = session.get(PolicyDecision, decision_id)
            return _decision_dict(row) if row is not None else None

    def decision_for_message(self, message_id: UUID) -> dict[str, Any] | None:
        with session_scope(self._sessions) as session:
            row = session.scalar(
                select(PolicyDecision)
                .where(PolicyDecision.message_id == message_id)
                .order_by(PolicyDecision.decided_at.desc())
                .limit(1)
            )
            return _decision_dict(row) if row is not None else None

    def case_for_message(self, message_id: UUID) -> dict[str, Any] | None:
        """Return the moderation case bound to a message, if one exists."""
        with session_scope(self._sessions) as session:
            row = session.scalar(
                select(ModerationCase).where(ModerationCase.message_id == message_id).limit(1)
            )
            return _case_dict(row) if row is not None else None

    def enforcement_for_decision(self, decision_id: UUID) -> dict[str, Any] | None:
        """Return the enforcement record produced by a decision, if any."""
        with session_scope(self._sessions) as session:
            row = session.scalar(
                select(EnforcementAction)
                .where(EnforcementAction.decision_id == decision_id)
                .order_by(EnforcementAction.created_at.desc())
                .limit(1)
            )
            return _enforcement_dict(row) if row is not None else None

    def list_decisions(
        self,
        *,
        status: str | None = None,
        action: str | None = None,
        requires_review: bool | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        statement = select(PolicyDecision).order_by(PolicyDecision.decided_at.desc())
        if status:
            statement = statement.where(PolicyDecision.decision_status == status)
        if action:
            statement = statement.where(PolicyDecision.action == action)
        if requires_review is not None:
            statement = statement.where(PolicyDecision.requires_review.is_(requires_review))
        statement = statement.limit(min(max(limit, 1), 1_000))
        with session_scope(self._sessions) as session:
            rows = session.scalars(statement).all()
        return [_decision_dict(row) for row in rows]

    def update_decision_status(
        self,
        decision_id: UUID,
        *,
        status: str,
        actor_ref: str,
        reason: str,
    ) -> dict[str, Any]:
        if status not in {item.value for item in GovernanceDecisionStatus}:
            raise GovernanceValidationError(f"unknown decision status: {status}")
        with session_scope(self._sessions) as session:
            row = session.get(PolicyDecision, decision_id)
            if row is None:
                raise GovernanceNotFoundError(f"decision not found: {decision_id}")
            before = _decision_dict(row)
            row.decision_status = status
            row.decided_by = actor_ref
            row.decision_reason = reason
            _audit(
                session,
                entity_type="policy_decision",
                entity_id=row.id,
                action="decision.status_changed",
                actor_ref=actor_ref,
                actor_role="moderator",
                reason=reason,
                before=before,
                after=_decision_dict(row),
            )
            session.flush()
            return _decision_dict(row)

    def record_decision_override(
        self,
        decision_id: UUID,
        *,
        actor_ref: str,
        actor_role: str,
        reason: str,
        status: str,
        action: str | None,
    ) -> dict[str, Any]:
        """Record a human decision override as a reviewable moderation event.

        A status-only override would leave the governance trace without a human
        review record. This path always links the override to a moderation case
        and review, while retaining the original decision and risk identifiers.
        """
        if status not in {item.value for item in GovernanceDecisionStatus}:
            raise GovernanceValidationError(f"unknown decision status: {status}")
        if action is not None and action not in {item.value for item in DecisionAction}:
            raise GovernanceValidationError(f"unknown decision action: {action}")
        _require_text(actor_ref, "actor_ref", 191)
        _require_text(actor_role, "actor_role", 32)
        _require_text(reason, "reason", 2_000)
        with session_scope(self._sessions) as session:
            decision = session.get(PolicyDecision, decision_id)
            if decision is None:
                raise GovernanceNotFoundError(f"decision not found: {decision_id}")
            before = _decision_dict(decision)
            explanation = dict(decision.explanation or {})
            evidence = dict(explanation.get("evidence") or {})
            valid_levels = {item.value for item in RiskSeverity}
            system_level = str(
                evidence.get("risk_level")
                or (
                    decision.reason_codes[1]
                    if decision.reason_codes and len(decision.reason_codes) > 1
                    else RiskSeverity.MEDIUM.value
                )
            )
            if system_level not in valid_levels:
                system_level = RiskSeverity.MEDIUM.value
            final_action = str(action or decision.action)
            now = datetime.now(UTC)

            case = session.scalar(
                select(ModerationCase).where(ModerationCase.message_id == decision.message_id)
            )
            if case is None:
                previous_status = None
                case = ModerationCase(
                    message_id=decision.message_id,
                    status=CaseStatus.FINALIZED.value,
                    priority=decision.priority,
                    decision_id=decision.id,
                    risk_result_id=decision.risk_result_id,
                    final_action=final_action,
                    final_level=system_level,
                    resolution=ModerationAction.OVERRIDE.value,
                    risk_snapshot={
                        "risk_score": float(decision.risk_score),
                        "risk_level": system_level,
                        "confidence": float(decision.confidence),
                        "suggested_action": str(decision.action),
                        "risk_result_id": (
                            str(decision.risk_result_id) if decision.risk_result_id else None
                        ),
                    },
                    opened_at=now,
                    closed_at=now,
                    is_synthetic=decision.is_synthetic,
                )
                session.add(case)
                session.flush()
                session.add(
                    CaseEvent(
                        case_id=case.id,
                        event_type="case.opened",
                        actor_type="user",
                        actor_ref=actor_ref,
                        from_status=None,
                        to_status=case.status,
                        note="case opened for decision override",
                    )
                )
            else:
                previous_status = str(case.status)
                case.decision_id = decision.id
                if case.risk_result_id is None:
                    case.risk_result_id = decision.risk_result_id
                case.status = CaseStatus.FINALIZED.value
                case.final_action = final_action
                case.final_level = system_level
                case.resolution = ModerationAction.OVERRIDE.value
                case.closed_at = now
                case.updated_at = now
                case.lock_version += 1
                session.add(
                    CaseEvent(
                        case_id=case.id,
                        event_type="moderation.override_recorded",
                        actor_type="user",
                        actor_ref=actor_ref,
                        from_status=previous_status,
                        to_status=case.status,
                        note=reason,
                    )
                )

            review = ModerationReview(
                case_id=case.id,
                decision_id=decision.id,
                reviewer_ref=actor_ref,
                reviewer_role=actor_role,
                action=ModerationAction.OVERRIDE.value,
                reason=reason,
                final_action=final_action,
                final_level=system_level,
                final_category=case.final_category,
                from_status=previous_status,
                to_status=case.status,
                system_action=str(decision.action),
                system_level=system_level,
                system_category=None,
                system_confidence=decision.confidence,
                is_synthetic=case.is_synthetic,
            )
            session.add(review)

            decision.decision_status = status
            decision.decided_by = actor_ref
            decision.decision_reason = reason
            explanation["human_review"] = {
                "reviewer": actor_ref,
                "role": actor_role,
                "action": ModerationAction.OVERRIDE.value,
                "reason": reason,
                "final_action": final_action,
                "final_level": system_level,
                "review_id": str(review.id),
                "case_id": str(case.id),
            }
            decision.explanation = explanation
            session.flush()

            after = _decision_dict(decision) | {
                "case_id": str(case.id),
                "review_id": str(review.id),
                "final_action": final_action,
            }
            _audit(
                session,
                entity_type="policy_decision",
                entity_id=decision.id,
                action="decision.overridden",
                actor_ref=actor_ref,
                actor_role=actor_role,
                reason=reason,
                before=before,
                after=after,
            )
            _audit(
                session,
                entity_type="moderation_case",
                entity_id=case.id,
                action="case.override_recorded",
                actor_ref=actor_ref,
                actor_role=actor_role,
                reason=reason,
                after=_case_dict(case) | {"review_id": str(review.id)},
            )
            _enqueue(
                session,
                OutboxDraft(
                    event_type="game.governance.decision.overridden.v1",
                    topic=self._topics.decision,
                    payload={
                        "synthetic": decision.is_synthetic,
                        "decision_id": str(decision.id),
                        "case_id": str(case.id),
                        "review_id": str(review.id),
                        "message_id": str(decision.message_id),
                        "risk_result_id": (
                            str(decision.risk_result_id) if decision.risk_result_id else None
                        ),
                        "system_action": str(decision.action),
                        "final_action": final_action,
                        "status": status,
                        "reviewer_ref": actor_ref,
                        "reviewer_role": actor_role,
                        "reason": reason,
                    },
                    dedupe_key=f"decision.override:{review.id}",
                    headers={"event_version": "1", "aggregate": "policy_decision"},
                ),
            )
            return after | {"created": True}

    def list_cases(
        self,
        *,
        statuses: list[str] | None = None,
        assignee: str | None = None,
        risk_level: str | None = None,
        overdue: bool = False,
        search: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        statement = select(ModerationCase, Message).join(
            Message, Message.id == ModerationCase.message_id
        )
        if statuses:
            statement = statement.where(ModerationCase.status.in_(statuses))
        if assignee == "unassigned":
            statement = statement.where(ModerationCase.assignee_ref.is_(None))
        elif assignee:
            statement = statement.where(ModerationCase.assignee_ref == assignee)
        statement = statement.order_by(ModerationCase.priority, ModerationCase.opened_at).limit(
            min(max(limit, 1), 1_000)
        )
        with session_scope(self._sessions) as session:
            rows = session.execute(statement).all()
        result: list[dict[str, Any]] = []
        needle = search.casefold().strip() if search else None
        for case, message in rows:
            level = _case_level(case, message)
            if risk_level and level != risk_level:
                continue
            if overdue and not (case.due_at is not None and case.due_at < now):
                continue
            if (
                needle
                and needle not in message.content.casefold()
                and needle not in (message.sender_ref.casefold())
            ):
                continue
            result.append(_case_summary(case, message, now))
        return result

    def case_detail(self, case_id: UUID) -> dict[str, Any]:
        with session_scope(self._sessions) as session:
            case = session.get(ModerationCase, case_id)
            if case is None:
                raise GovernanceNotFoundError(f"case not found: {case_id}")
            message = session.get(Message, case.message_id)
            decision = session.get(PolicyDecision, case.decision_id) if case.decision_id else None
            risk = session.get(RiskResult, case.risk_result_id) if case.risk_result_id else None
            if risk is None and message is not None:
                risk = session.scalar(select(RiskResult).where(RiskResult.message_id == message.id))
            label = (
                session.scalar(select(MessageLabel).where(MessageLabel.message_id == message.id))
                if message is not None
                else None
            )
            return {
                "case": _case_summary(case, message, datetime.now(UTC)) if message else {},
                "message": _message_dict(message) if message else None,
                "risk": _risk_dict(risk, list(risk.categories or [])) if risk else None,
                "label": (
                    {"label": label.label, "risk_category": label.risk_category}
                    if label is not None
                    else None
                ),
                "decision": _decision_dict(decision) if decision is not None else None,
                "evaluation": self._evaluation_for_decision(session, decision),
                "reviews": [_review_dict(item) for item in case.reviews],
                "events": [
                    _event_dict(item) for item in sorted(case.events, key=lambda x: x.created_at)
                ],
                "enforcements": [
                    _enforcement_dict(item)
                    for item in sorted(
                        case.enforcement_actions, key=lambda x: x.created_at, reverse=True
                    )
                ],
                "feedback": [
                    _feedback_dict(item)
                    for item in session.scalars(
                        select(GovernanceFeedback)
                        .where(GovernanceFeedback.message_id == case.message_id)
                        .order_by(GovernanceFeedback.created_at.desc())
                    )
                ],
                "audit": _audit_rows(session, case.message_id, 50),
            }

    @staticmethod
    def _evaluation_for_decision(
        session: Session, decision: PolicyDecision | None
    ) -> dict[str, Any] | None:
        if decision is None or decision.policy_evaluation_id is None:
            return None
        row = session.get(PolicyEvaluation, decision.policy_evaluation_id)
        return _evaluation_dict(row) if row is not None else None

    def claim_case(
        self,
        case_id: UUID,
        *,
        reviewer_ref: str,
        reviewer_role: str,
        expected_lock_version: int | None = None,
    ) -> dict[str, Any]:
        _require_text(reviewer_ref, "reviewer_ref", 191)
        _require_text(reviewer_role, "reviewer_role", 32)
        with session_scope(self._sessions) as session:
            case = session.scalar(
                select(ModerationCase).where(ModerationCase.id == case_id).with_for_update()
            )
            if case is None:
                raise GovernanceNotFoundError(f"case not found: {case_id}")
            if case.status == CaseStatus.IN_REVIEW.value and case.assignee_ref == reviewer_ref:
                return _case_dict(case)
            if expected_lock_version is not None and case.lock_version != expected_lock_version:
                raise ModerationConflictError(
                    "case was modified by another reviewer; reload before claiming"
                )
            validate_claim(case.status, case.assignee_ref, reviewer_ref)
            before = _case_dict(case)
            case.assignee_ref = reviewer_ref
            previous = case.status
            case.status = CaseStatus.IN_REVIEW.value
            case.lock_version += 1
            case.updated_at = datetime.now(UTC)
            session.add(
                CaseEvent(
                    case_id=case.id,
                    event_type="case.claimed",
                    actor_type="user",
                    actor_ref=reviewer_ref,
                    from_status=previous,
                    to_status=case.status,
                    note=f"claimed by {reviewer_ref} ({reviewer_role})",
                )
            )
            _audit(
                session,
                entity_type="moderation_case",
                entity_id=case.id,
                action="case.claimed",
                actor_ref=reviewer_ref,
                actor_role=reviewer_role,
                reason="case claimed for review",
                before=before,
                after=_case_dict(case),
            )
            session.flush()
            return _case_dict(case)

    def review_case(
        self,
        case_id: UUID,
        *,
        reviewer_ref: str,
        reviewer_role: str,
        action: str,
        reason: str,
        final_action: str | None = None,
        final_level: str | None = None,
        final_category: str | None = None,
        notes: str | None = None,
        expected_lock_version: int | None = None,
    ) -> dict[str, Any]:
        _require_text(reviewer_ref, "reviewer_ref", 191)
        _require_text(reviewer_role, "reviewer_role", 32)
        with session_scope(self._sessions) as session:
            case = session.scalar(
                select(ModerationCase).where(ModerationCase.id == case_id).with_for_update()
            )
            if case is None:
                raise GovernanceNotFoundError(f"case not found: {case_id}")
            if expected_lock_version is not None and case.lock_version != expected_lock_version:
                raise ModerationConflictError(
                    "case was modified by another reviewer; reload before submitting"
                )
            if case.assignee_ref and case.assignee_ref != reviewer_ref:
                raise ModerationConflictError(
                    f"case is assigned to {case.assignee_ref}; only that reviewer may decide"
                )
            decision = session.get(PolicyDecision, case.decision_id) if case.decision_id else None
            snapshot = case.risk_snapshot or {}
            system_action = (
                decision.action
                if decision is not None
                else str(snapshot.get("suggested_action", DecisionAction.REVIEW.value))
            )
            system_level = str(
                snapshot.get("risk_level")
                or (
                    decision.reason_codes[1]
                    if decision is not None and len(decision.reason_codes or []) > 1
                    else RiskSeverity.MEDIUM.value
                )
            )
            raw_categories = snapshot.get("categories") or []
            first_category = raw_categories[0] if raw_categories else None
            if isinstance(first_category, dict):
                system_category = str(first_category.get("db_category")) if first_category else None
            elif isinstance(first_category, str):
                system_category = first_category
            else:
                system_category = None
            try:
                outcome = build_review_outcome(
                    current_status=case.status,
                    action=action,
                    reason=reason,
                    system_action=system_action,
                    system_level=system_level,
                    system_category=system_category,
                    final_action=final_action,
                    final_level=final_level,
                    final_category=final_category,
                )
            except ModerationWorkflowError as error:
                raise GovernanceValidationError(str(error)) from error
            before = _case_dict(case)
            previous = case.status
            now = datetime.now(UTC)
            case.status = outcome.target_status
            case.final_action = outcome.final_action
            case.final_level = outcome.final_level
            case.final_category = outcome.final_category
            case.required_second_review = outcome.requires_second_review
            case.resolution = action
            if outcome.target_status in {
                CaseStatus.APPROVED.value,
                CaseStatus.REJECTED.value,
                CaseStatus.FINALIZED.value,
            }:
                case.closed_at = now
            elif action == "reopen":
                case.closed_at = None
                case.reopened_count += 1
            case.lock_version += 1
            case.updated_at = now
            review = ModerationReview(
                case_id=case.id,
                decision_id=decision.id if decision is not None else None,
                reviewer_ref=reviewer_ref,
                reviewer_role=reviewer_role,
                action=action,
                reason=reason,
                final_category=outcome.final_category,
                final_level=outcome.final_level,
                final_action=outcome.final_action,
                notes=notes,
                from_status=previous,
                to_status=case.status,
                system_action=system_action,
                system_category=system_category,
                system_level=system_level,
                system_confidence=decision.confidence if decision is not None else None,
                is_synthetic=case.is_synthetic,
            )
            session.add(review)
            session.add(
                CaseEvent(
                    case_id=case.id,
                    event_type=f"moderation.{action}",
                    actor_type="user",
                    actor_ref=reviewer_ref,
                    from_status=previous,
                    to_status=case.status,
                    note=reason,
                )
            )
            if decision is not None:
                decision.decision_status = (
                    outcome.decision_status or GovernanceDecisionStatus.PENDING_REVIEW.value
                )
                decision.decided_by = reviewer_ref
                decision.decision_reason = reason
                explanation = dict(decision.explanation or {})
                explanation["human_review"] = {
                    "reviewer": reviewer_ref,
                    "role": reviewer_role,
                    "action": action,
                    "reason": reason,
                    "final_action": outcome.final_action,
                    "final_level": outcome.final_level,
                }
                decision.explanation = explanation
            session.flush()
            _audit(
                session,
                entity_type="moderation_case",
                entity_id=case.id,
                action=f"case.{action}",
                actor_ref=reviewer_ref,
                actor_role=reviewer_role,
                reason=reason,
                before=before,
                after=_case_dict(case),
            )
            _enqueue(
                session,
                OutboxDraft(
                    event_type="game.governance.moderation.reviewed.v1",
                    topic=self._topics.moderation,
                    payload={
                        "synthetic": case.is_synthetic,
                        "case_id": str(case.id),
                        "review_id": str(review.id),
                        "message_id": str(case.message_id),
                        "decision_id": str(decision.id) if decision is not None else None,
                        "action": action,
                        "from_status": previous,
                        "to_status": case.status,
                        "final_action": outcome.final_action,
                        "final_level": outcome.final_level,
                        "reviewer_ref": reviewer_ref,
                        "reviewer_role": reviewer_role,
                        "reason": reason,
                    },
                    dedupe_key=f"moderation.reviewed:{review.id}",
                    headers={"event_version": "1", "aggregate": "moderation_case"},
                ),
            )
            return _case_dict(case) | {
                "review": _review_dict(review),
                "decision_status": (decision.decision_status if decision is not None else None),
            }

    def list_reviews(self, case_id: UUID) -> list[dict[str, Any]]:
        with session_scope(self._sessions) as session:
            rows = session.scalars(
                select(ModerationReview)
                .where(ModerationReview.case_id == case_id)
                .order_by(ModerationReview.created_at)
            ).all()
            return [_review_dict(row) for row in rows]

    def case_events(self, case_id: UUID) -> list[dict[str, Any]]:
        with session_scope(self._sessions) as session:
            rows = session.scalars(
                select(CaseEvent).where(CaseEvent.case_id == case_id).order_by(CaseEvent.created_at)
            ).all()
            return [_event_dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Enforcement
    # ------------------------------------------------------------------
    def execute_enforcement(
        self,
        *,
        decision_id: UUID,
        action: str,
        target_ref: str,
        target_type: str | None,
        duration_seconds: int | None,
        reason: str,
        actor_ref: str,
        idempotency_key: str,
        scope_ref: str | None = None,
        simulate: bool = True,
        force_failure: bool = False,
    ) -> dict[str, Any]:
        _require_text(target_ref, "target_ref", 191)
        _require_text(reason, "reason", 2_000)
        _require_text(actor_ref, "actor_ref", 191)
        _require_text(idempotency_key, "idempotency_key", 191)
        with session_scope(self._sessions) as session:
            existing = session.scalar(
                select(EnforcementAction).where(
                    EnforcementAction.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                return _enforcement_dict(existing) | {"created": False}
            decision = session.get(PolicyDecision, decision_id)
            if decision is None:
                raise GovernanceNotFoundError(f"decision not found: {decision_id}")
            message = session.get(Message, decision.message_id)
            if message is None:
                raise GovernanceNotFoundError(f"message not found: {decision.message_id}")
            now = datetime.now(UTC)
            try:
                plan = plan_enforcement(
                    action=action,
                    target_type=target_type,
                    duration_seconds=duration_seconds,
                    now=now,
                    simulate=simulate,
                )
                validate_target_ref(action, target_ref, message_id=str(message.id))
            except EnforcementValidationError as error:
                raise GovernanceValidationError(str(error)) from error
            case = session.scalar(
                select(ModerationCase).where(ModerationCase.message_id == message.id)
            )
            review = (
                session.scalar(
                    select(ModerationReview)
                    .where(ModerationReview.case_id == case.id)
                    .order_by(ModerationReview.created_at.desc())
                )
                if case is not None
                else None
            )
            trace = {
                "message_id": str(message.id),
                "decision_id": str(decision.id),
                "case_id": str(case.id) if case is not None else None,
                "review_id": str(review.id) if review is not None else None,
                "policy_id": str(decision.policy_id),
                "policy_version": _policy_version(session, decision),
                "risk_result_id": (
                    str(decision.risk_result_id) if decision.risk_result_id else None
                ),
            }
            allowed_actions = {str(decision.action)}
            if case is not None and case.final_action is not None:
                allowed_actions.add(str(case.final_action))
            if action not in allowed_actions:
                raise GovernanceValidationError(
                    f"action '{action}' does not match the decision or reviewed final action "
                    f"{sorted(allowed_actions)}"
                )
            if decision.action == DecisionAction.REVIEW.value:
                if case is None or case.status not in {
                    CaseStatus.APPROVED.value,
                    CaseStatus.FINALIZED.value,
                }:
                    raise GovernanceValidationError(
                        "a review decision must be approved before enforcement"
                    )
                if action != str(case.final_action):
                    raise GovernanceValidationError(
                        "enforcement action must equal the reviewer's final action"
                    )
            duplicate = session.scalar(
                select(EnforcementAction).where(
                    EnforcementAction.decision_id == decision.id,
                    EnforcementAction.action_type == action,
                    EnforcementAction.target_ref == target_ref,
                    EnforcementAction.status.in_(
                        [EnforcementStatus.PENDING.value, EnforcementStatus.EXECUTED.value]
                    ),
                )
            )
            if duplicate is not None:
                return _enforcement_dict(duplicate) | {"created": False, "duplicate": True}
            row = EnforcementAction(
                decision_id=decision.id,
                case_id=case.id if case is not None else None,
                idempotency_key=idempotency_key,
                action_type=action,
                target_ref=target_ref,
                status=(
                    EnforcementStatus.FAILED.value
                    if force_failure
                    else EnforcementStatus.EXECUTED.value
                ),
                executed_at=None if force_failure else now,
                details={
                    "synthetic": True,
                    "simulated": True,
                    "scope_ref": scope_ref,
                    "trace": trace,
                },
                target_type=plan.target_type,
                server_ref=message.server_ref,
                duration_seconds=plan.duration_seconds,
                reason=reason,
                expires_at=plan.expires_at,
                simulated=True,
                is_synthetic=decision.is_synthetic or message.is_synthetic,
            )
            session.add(row)
            session.flush()
            if force_failure:
                row.details = {
                    **row.details,
                    "error": "simulated enforcement failure requested by operator",
                }
                _audit(
                    session,
                    entity_type="enforcement_action",
                    entity_id=row.id,
                    action="enforcement.failed",
                    actor_ref=actor_ref,
                    actor_role="operator",
                    reason=reason,
                    after=_enforcement_dict(row),
                )
                _enqueue(
                    session,
                    OutboxDraft(
                        event_type="game.governance.enforcement.failed.v1",
                        topic=self._topics.enforcement,
                        payload={
                            "synthetic": True,
                            "simulated": True,
                            "simulated_only": True,
                            "enforcement_id": str(row.id),
                            "action": action,
                            "target_ref": target_ref,
                            "reason": reason,
                            **trace,
                        },
                        dedupe_key=f"enforcement.failed:{row.id}",
                        headers={"event_version": "1", "aggregate": "enforcement_action"},
                    ),
                )
                return _enforcement_dict(row) | {"created": True}
            if action == DecisionAction.BLOCK.value:
                message.display_status = MessageDisplayStatus.BLOCKED.value
            player_state = None
            if plan.target_type != "message":
                player_state = self._apply_player_state(
                    session,
                    row,
                    action=action,
                    target_ref=target_ref,
                    scope_ref=scope_ref or message.server_ref or "*",
                    server_ref=message.server_ref,
                    now=now,
                )
            _audit(
                session,
                entity_type="enforcement_action",
                entity_id=row.id,
                action="enforcement.executed",
                actor_ref=actor_ref,
                actor_role="operator",
                reason=reason,
                after=_enforcement_dict(row) | {"player_state": player_state},
            )
            _enqueue(
                session,
                OutboxDraft(
                    event_type="game.governance.enforcement.executed.v1",
                    topic=self._topics.enforcement,
                    payload={
                        "synthetic": True,
                        "simulated": True,
                        "simulated_only": True,
                        "enforcement_id": str(row.id),
                        "action": action,
                        "target_ref": target_ref,
                        "target_type": plan.target_type,
                        "duration_seconds": plan.duration_seconds,
                        "expires_at": (plan.expires_at.isoformat() if plan.expires_at else None),
                        "executed_at": now.isoformat(),
                        **trace,
                    },
                    dedupe_key=f"enforcement.executed:{row.id}",
                    headers={"event_version": "1", "aggregate": "enforcement_action"},
                ),
            )
            session.flush()
            return _enforcement_dict(row) | {"created": True, "player_state": player_state}

    def _apply_player_state(
        self,
        session: Session,
        enforcement: EnforcementAction,
        *,
        action: str,
        target_ref: str,
        scope_ref: str,
        server_ref: str | None,
        now: datetime,
    ) -> dict[str, Any]:
        state = session.scalar(
            select(PlayerEnforcementState)
            .where(
                PlayerEnforcementState.player_ref == target_ref,
                PlayerEnforcementState.scope_ref == scope_ref,
            )
            .with_for_update()
        )
        if state is None:
            state = PlayerEnforcementState(
                player_ref=target_ref,
                scope_ref=scope_ref,
                server_ref=server_ref,
                is_synthetic=True,
            )
            session.add(state)
        state.server_ref = server_ref
        state.last_enforcement_id = enforcement.id
        state.updated_at = now
        if action == DecisionAction.WARN.value:
            state.warn_count = (state.warn_count or 0) + 1
        elif action == DecisionAction.MUTE.value and enforcement.expires_at is not None:
            state.mute_until = _later(state.mute_until, enforcement.expires_at)
        elif action == DecisionAction.TEMP_BAN.value and enforcement.expires_at is not None:
            state.ban_until = _later(state.ban_until, enforcement.expires_at)
        elif action == DecisionAction.PERM_BAN.value:
            state.permanent_ban = True
            state.ban_until = None
        session.flush()
        return _player_state_dict(state)

    def release_enforcement(
        self,
        enforcement_id: UUID,
        *,
        actor_ref: str,
        reason: str,
    ) -> dict[str, Any]:
        _require_text(actor_ref, "actor_ref", 191)
        _require_text(reason, "reason", 2_000)
        with session_scope(self._sessions) as session:
            row = session.get(EnforcementAction, enforcement_id)
            if row is None:
                raise GovernanceNotFoundError(f"enforcement not found: {enforcement_id}")
            if row.status not in {
                EnforcementStatus.EXECUTED.value,
                EnforcementStatus.PENDING.value,
            }:
                raise GovernanceValidationError(
                    f"enforcement in status '{row.status}' cannot be released"
                )
            now = datetime.now(UTC)
            before = _enforcement_dict(row)
            trace = dict((row.details or {}).get("trace") or {})
            row.status = EnforcementStatus.RELEASED.value
            row.released_at = now
            row.release_reason = reason
            if row.target_type != "message":
                states = session.scalars(
                    select(PlayerEnforcementState).where(
                        PlayerEnforcementState.last_enforcement_id == row.id
                    )
                ).all()
                for state in states:
                    if state.permanent_ban:
                        state.permanent_ban = False
                    state.mute_until = None
                    state.ban_until = None
                    state.updated_at = now
            _audit(
                session,
                entity_type="enforcement_action",
                entity_id=row.id,
                action="enforcement.released",
                actor_ref=actor_ref,
                actor_role="operator",
                reason=reason,
                before=before,
                after=_enforcement_dict(row),
            )
            _enqueue(
                session,
                OutboxDraft(
                    event_type="game.governance.enforcement.released.v1",
                    topic=self._topics.enforcement,
                    payload={
                        "synthetic": True,
                        "simulated": True,
                        "simulated_only": True,
                        "enforcement_id": str(row.id),
                        "action": row.action_type,
                        "target_ref": row.target_ref,
                        "reason": reason,
                        "released_at": now.isoformat(),
                        **trace,
                    },
                    dedupe_key=f"enforcement.released:{row.id}",
                    headers={"event_version": "1", "aggregate": "enforcement_action"},
                ),
            )
            session.flush()
            return _enforcement_dict(row)

    def expire_due_enforcements(self, *, limit: int = 500) -> int:
        now = datetime.now(UTC)
        with session_scope(self._sessions) as session:
            rows = session.scalars(
                select(EnforcementAction)
                .where(
                    EnforcementAction.status == EnforcementStatus.EXECUTED.value,
                    EnforcementAction.expires_at.is_not(None),
                    EnforcementAction.expires_at <= now,
                )
                .order_by(EnforcementAction.expires_at)
                .limit(min(max(limit, 1), 5_000))
                .with_for_update(skip_locked=True)
            ).all()
            for row in rows:
                before = _enforcement_dict(row)
                trace = dict((row.details or {}).get("trace") or {})
                row.status = EnforcementStatus.EXPIRED.value
                if row.target_type != "message":
                    states = session.scalars(
                        select(PlayerEnforcementState).where(
                            PlayerEnforcementState.last_enforcement_id == row.id
                        )
                    ).all()
                    for state in states:
                        state.mute_until = None
                        state.ban_until = None
                        state.updated_at = now
                _audit(
                    session,
                    entity_type="enforcement_action",
                    entity_id=row.id,
                    action="enforcement.expired",
                    actor_ref="governance-engine",
                    actor_role="system",
                    reason="simulated enforcement expired",
                    before=before,
                    after=_enforcement_dict(row),
                )
                _enqueue(
                    session,
                    OutboxDraft(
                        event_type="game.governance.enforcement.expired.v1",
                        topic=self._topics.enforcement,
                        payload={
                            "synthetic": True,
                            "simulated": True,
                            "simulated_only": True,
                            "enforcement_id": str(row.id),
                            "action": row.action_type,
                            "target_ref": row.target_ref,
                            "expired_at": now.isoformat(),
                            **trace,
                        },
                        dedupe_key=f"enforcement.expired:{row.id}",
                        headers={"event_version": "1", "aggregate": "enforcement_action"},
                    ),
                )
            return len(rows)

    def list_enforcements(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with session_scope(self._sessions) as session:
            rows = session.scalars(
                select(EnforcementAction)
                .order_by(EnforcementAction.created_at.desc())
                .limit(min(max(limit, 1), 1_000))
            ).all()
            return [_enforcement_dict(row) for row in rows]

    def get_enforcement(self, enforcement_id: UUID) -> dict[str, Any] | None:
        with session_scope(self._sessions) as session:
            row = session.get(EnforcementAction, enforcement_id)
            return _enforcement_dict(row) if row is not None else None

    def player_states(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with session_scope(self._sessions) as session:
            rows = session.scalars(
                select(PlayerEnforcementState)
                .order_by(PlayerEnforcementState.updated_at.desc())
                .limit(min(max(limit, 1), 1_000))
            ).all()
            return [_player_state_dict(row) for row in rows]

    def player_state(self, player_ref: str, scope_ref: str = "*") -> dict[str, Any] | None:
        with session_scope(self._sessions) as session:
            row = session.scalar(
                select(PlayerEnforcementState).where(
                    PlayerEnforcementState.player_ref == player_ref,
                    PlayerEnforcementState.scope_ref == scope_ref,
                )
            )
            return _player_state_dict(row) if row is not None else None

    # ------------------------------------------------------------------
    # Feedback and audit
    # ------------------------------------------------------------------
    def create_feedback(
        self,
        *,
        message_id: UUID,
        decision_id: UUID | None,
        review_id: UUID | None,
        feedback_type: str,
        difference_reason: str,
        final_risk: dict[str, Any],
        reviewer_ref: str,
        is_synthetic: bool,
    ) -> dict[str, Any]:
        if feedback_type not in {item.value for item in FeedbackType}:
            raise GovernanceValidationError(f"unknown feedback type: {feedback_type}")
        _require_text(difference_reason, "difference_reason", 4_000)
        _require_text(reviewer_ref, "reviewer_ref", 191)
        with session_scope(self._sessions) as session:
            message = session.get(Message, message_id)
            if message is None:
                raise GovernanceNotFoundError(f"message not found: {message_id}")
            risk = session.scalar(select(RiskResult).where(RiskResult.message_id == message_id))
            decision = session.get(PolicyDecision, decision_id) if decision_id else None
            row = GovernanceFeedback(
                message_id=message_id,
                decision_id=decision.id if decision is not None else None,
                review_id=review_id,
                feedback_type=feedback_type,
                difference_reason=difference_reason,
                original_prediction=(
                    {
                        "risk_result_id": str(risk.id),
                        "risk_score": float(risk.risk_score),
                        "risk_level": str(risk.risk_level),
                        "suggested_action": str(risk.suggested_action),
                        "confidence": float(risk.confidence),
                        "categories": list(risk.categories or []),
                        "model_id": risk.ml_model_id,
                    }
                    if risk is not None
                    else {}
                ),
                original_risk=(
                    {
                        "risk_score": float(risk.risk_score),
                        "risk_level": str(risk.risk_level),
                        "confidence": float(risk.confidence),
                    }
                    if risk is not None
                    else {}
                ),
                final_risk=final_risk,
                policy_version=(
                    _policy_version(session, decision) if decision is not None else None
                ),
                model_version=risk.ml_model_id if risk is not None else None,
                reviewer_ref=reviewer_ref,
                is_synthetic=is_synthetic,
            )
            session.add(row)
            session.flush()
            _audit(
                session,
                entity_type="governance_feedback",
                entity_id=row.id,
                action="feedback.created",
                actor_ref=reviewer_ref,
                actor_role="moderator",
                reason=difference_reason,
                after=_feedback_dict(row),
            )
            _enqueue(
                session,
                OutboxDraft(
                    event_type="game.governance.feedback.created.v1",
                    topic=self._topics.feedback,
                    payload={
                        "synthetic": is_synthetic,
                        "feedback_id": str(row.id),
                        "message_id": str(message_id),
                        "decision_id": str(decision.id) if decision is not None else None,
                        "feedback_type": feedback_type,
                        "reviewer_ref": reviewer_ref,
                    },
                    dedupe_key=f"feedback.created:{row.id}",
                    headers={"event_version": "1", "aggregate": "governance_feedback"},
                ),
            )
            return _feedback_dict(row)

    def list_feedback(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with session_scope(self._sessions) as session:
            rows = session.scalars(
                select(GovernanceFeedback)
                .order_by(GovernanceFeedback.created_at.desc())
                .limit(min(max(limit, 1), 1_000))
            ).all()
            return [_feedback_dict(row) for row in rows]

    def feedback_stats(self) -> dict[str, Any]:
        with session_scope(self._sessions) as session:
            by_type = {
                str(kind): int(count)
                for kind, count in session.execute(
                    select(GovernanceFeedback.feedback_type, func.count()).group_by(
                        GovernanceFeedback.feedback_type
                    )
                )
            }
            total = sum(by_type.values())
            false_positive = by_type.get(FeedbackType.FALSE_POSITIVE.value, 0)
            false_negative = by_type.get(FeedbackType.FALSE_NEGATIVE.value, 0)
            correct = by_type.get(FeedbackType.CORRECT.value, 0)
            model_versions = {
                str(version): int(count)
                for version, count in session.execute(
                    select(GovernanceFeedback.model_version, func.count())
                    .where(GovernanceFeedback.model_version.is_not(None))
                    .group_by(GovernanceFeedback.model_version)
                )
            }
        return {
            "total": total,
            "by_type": by_type,
            "correct_rate": round(correct / total, 4) if total else None,
            "false_positive_rate": round(false_positive / total, 4) if total else None,
            "false_negative_rate": round(false_negative / total, 4) if total else None,
            "model_versions": model_versions,
        }

    def list_audit(
        self,
        *,
        entity_type: str | None = None,
        action: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        statement = select(AuditEvent).order_by(AuditEvent.created_at.desc())
        if entity_type:
            statement = statement.where(AuditEvent.entity_type == entity_type)
        if action:
            statement = statement.where(AuditEvent.action == action)
        statement = statement.limit(min(max(limit, 1), 1_000))
        with session_scope(self._sessions) as session:
            return [_audit_dict(row) for row in session.scalars(statement)]

    # ------------------------------------------------------------------
    # Outbox
    # ------------------------------------------------------------------
    def pending_outbox(self, *, limit: int = 100, max_attempts: int = 5) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        with session_scope(self._sessions) as session:
            rows = session.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.available_at <= now,
                    OutboxEvent.attempts < max_attempts,
                    OutboxEvent.status.in_([OutboxStatus.PENDING.value, OutboxStatus.FAILED.value]),
                )
                .order_by(OutboxEvent.available_at)
                .limit(min(max(limit, 1), 1_000))
            ).all()
            return [_outbox_dict(row) for row in rows]

    def mark_outbox_published(self, event_id: UUID) -> None:
        with session_scope(self._sessions) as session:
            row = session.get(OutboxEvent, event_id)
            if row is None:
                raise GovernanceNotFoundError(f"outbox event not found: {event_id}")
            row.status = OutboxStatus.PUBLISHED.value
            row.published_at = datetime.now(UTC)
            row.attempts += 1
            row.last_error = None

    def mark_outbox_failed(
        self, event_id: UUID, *, error: str, retry_delay_seconds: int = 30
    ) -> None:
        with session_scope(self._sessions) as session:
            row = session.get(OutboxEvent, event_id)
            if row is None:
                raise GovernanceNotFoundError(f"outbox event not found: {event_id}")
            row.attempts += 1
            row.status = OutboxStatus.FAILED.value
            row.last_error = error[:4_000]
            row.available_at = datetime.now(UTC) + timedelta(seconds=retry_delay_seconds)

    def enqueue_event(self, draft: OutboxDraft) -> dict[str, Any]:
        """Persist an outbox event so it is published after the transaction commits."""
        if not isinstance(draft.topic, str) or not draft.topic.strip():
            raise GovernanceValidationError("outbox event topic must not be empty")
        if not isinstance(draft.event_type, str) or not draft.event_type.strip():
            raise GovernanceValidationError("outbox event_type must not be empty")
        with session_scope(self._sessions) as session:
            _enqueue(session, draft)
            session.flush()
            row = session.scalar(
                select(OutboxEvent).where(OutboxEvent.dedupe_key == draft.dedupe_key)
            )
            if row is None:
                raise GovernanceNotFoundError("outbox event was not persisted")
            return _outbox_dict(row)

    def outbox_stats(self) -> dict[str, Any]:
        with session_scope(self._sessions) as session:
            by_status = {
                str(status): int(count)
                for status, count in session.execute(
                    select(OutboxEvent.status, func.count()).group_by(OutboxEvent.status)
                )
            }
            oldest = session.scalar(
                select(func.min(OutboxEvent.created_at)).where(
                    OutboxEvent.status == OutboxStatus.PENDING.value
                )
            )
            recent_errors = [
                {
                    "event_id": str(row.id),
                    "event_type": row.event_type,
                    "attempts": row.attempts,
                    "last_error": row.last_error,
                    "available_at": row.available_at.isoformat(),
                }
                for row in session.scalars(
                    select(OutboxEvent)
                    .where(OutboxEvent.status == OutboxStatus.FAILED.value)
                    .order_by(OutboxEvent.available_at.desc())
                    .limit(10)
                )
            ]
        return {
            "by_status": by_status,
            "pending_oldest": oldest.isoformat() if oldest else None,
            "recent_errors": recent_errors,
        }

    # ------------------------------------------------------------------
    # Dashboard and traceability
    # ------------------------------------------------------------------
    def governance_stats(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        with session_scope(self._sessions) as session:
            decisions_by_status = {
                str(status or "legacy"): int(count)
                for status, count in session.execute(
                    select(PolicyDecision.decision_status, func.count()).group_by(
                        PolicyDecision.decision_status
                    )
                )
            }
            decisions_by_action = {
                str(action): int(count)
                for action, count in session.execute(
                    select(PolicyDecision.action, func.count())
                    .where(PolicyDecision.decision_status.is_not(None))
                    .group_by(PolicyDecision.action)
                )
            }
            cases_by_status = {
                str(status): int(count)
                for status, count in session.execute(
                    select(ModerationCase.status, func.count()).group_by(ModerationCase.status)
                )
            }
            overdue = int(
                session.scalar(
                    select(func.count())
                    .select_from(ModerationCase)
                    .where(
                        ModerationCase.status.in_(
                            [
                                CaseStatus.PENDING.value,
                                CaseStatus.IN_REVIEW.value,
                                CaseStatus.ESCALATED.value,
                                CaseStatus.SECOND_REVIEW.value,
                            ]
                        ),
                        ModerationCase.due_at.is_not(None),
                        ModerationCase.due_at < now,
                    )
                )
                or 0
            )
            enforcement_by_status = {
                str(status): int(count)
                for status, count in session.execute(
                    select(EnforcementAction.status, func.count()).group_by(
                        EnforcementAction.status
                    )
                )
            }
            enforcement_by_action = {
                str(action): int(count)
                for action, count in session.execute(
                    select(EnforcementAction.action_type, func.count()).group_by(
                        EnforcementAction.action_type
                    )
                )
            }
            evaluations = int(
                session.scalar(select(func.count()).select_from(PolicyEvaluation)) or 0
            )
            reviewed_cases = int(
                session.scalar(select(func.count()).select_from(ModerationReview)) or 0
            )
            open_cases = sum(
                cases_by_status.get(status, 0)
                for status in (
                    CaseStatus.PENDING.value,
                    CaseStatus.IN_REVIEW.value,
                    CaseStatus.ESCALATED.value,
                    CaseStatus.SECOND_REVIEW.value,
                )
            )
        return {
            "evaluations": evaluations,
            "decisions_by_status": decisions_by_status,
            "decisions_by_action": decisions_by_action,
            "cases_by_status": cases_by_status,
            "open_cases": open_cases,
            "overdue_cases": overdue,
            "reviews": reviewed_cases,
            "enforcement_by_status": enforcement_by_status,
            "enforcement_by_action": enforcement_by_action,
            "feedback": self.feedback_stats(),
            "outbox": self.outbox_stats(),
        }

    def governance_trace(self, message_id: UUID) -> dict[str, Any]:
        with session_scope(self._sessions) as session:
            message = session.get(Message, message_id)
            if message is None:
                raise GovernanceNotFoundError(f"message not found: {message_id}")
            risk = session.scalar(select(RiskResult).where(RiskResult.message_id == message_id))
            evaluations = session.scalars(
                select(PolicyEvaluation)
                .where(PolicyEvaluation.message_id == message_id)
                .order_by(PolicyEvaluation.evaluated_at)
            ).all()
            decisions = session.scalars(
                select(PolicyDecision)
                .where(PolicyDecision.message_id == message_id)
                .order_by(PolicyDecision.decided_at)
            ).all()
            case = session.scalar(
                select(ModerationCase).where(ModerationCase.message_id == message_id)
            )
            enforcements = session.scalars(
                select(EnforcementAction)
                .join(PolicyDecision, PolicyDecision.id == EnforcementAction.decision_id)
                .where(PolicyDecision.message_id == message_id)
                .order_by(EnforcementAction.created_at)
            ).all()
            feedback = session.scalars(
                select(GovernanceFeedback)
                .where(GovernanceFeedback.message_id == message_id)
                .order_by(GovernanceFeedback.created_at)
            ).all()
            audits = session.scalars(
                select(AuditEvent)
                .where(
                    or_(
                        AuditEvent.entity_id == message_id,
                        AuditEvent.entity_id.in_([item.id for item in decisions]),
                        AuditEvent.entity_id.in_([item.id for item in evaluations]),
                        AuditEvent.entity_id.in_([item.id for item in enforcements]),
                        AuditEvent.entity_id == (case.id if case is not None else uuid4()),
                    )
                )
                .order_by(AuditEvent.created_at)
            ).all()
            return {
                "message": _message_dict(message),
                "risk": _risk_dict(risk, list(risk.categories or [])) if risk else None,
                "evaluations": [_evaluation_dict(item) for item in evaluations],
                "decisions": [_decision_dict(item) for item in decisions],
                "case": _case_dict(case) if case is not None else None,
                "reviews": (
                    [
                        _review_dict(item)
                        for item in sorted(case.reviews, key=lambda x: x.created_at)
                    ]
                    if case is not None
                    else []
                ),
                "enforcements": [_enforcement_dict(item) for item in enforcements],
                "feedback": [_feedback_dict(item) for item in feedback],
                "audit": [_audit_dict(item) for item in audits],
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _create_case(self, session: Session, decision: PolicyDecision, draft: CaseDraft) -> UUID:
        existing = session.scalar(
            select(ModerationCase).where(ModerationCase.message_id == decision.message_id)
        )
        if existing is not None:
            if existing.decision_id is None:
                existing.decision_id = decision.id
            if existing.risk_result_id is None:
                existing.risk_result_id = decision.risk_result_id
            if existing.risk_snapshot is None:
                existing.risk_snapshot = draft.risk_snapshot
            return existing.id
        now = datetime.now(UTC)
        terminal = draft.status in {
            CaseStatus.APPROVED.value,
            CaseStatus.REJECTED.value,
            CaseStatus.FINALIZED.value,
        }
        case = ModerationCase(
            message_id=decision.message_id,
            status=draft.status,
            priority=draft.priority,
            decision_id=decision.id,
            risk_result_id=decision.risk_result_id,
            required_second_review=draft.required_second_review,
            due_at=draft.due_at,
            final_category=draft.final_category,
            final_level=draft.final_level,
            final_action=draft.final_action,
            risk_snapshot=draft.risk_snapshot,
            opened_at=now,
            closed_at=now if terminal else None,
            resolution="auto" if terminal else None,
            is_synthetic=decision.is_synthetic,
        )
        session.add(case)
        session.flush()
        session.add(
            CaseEvent(
                case_id=case.id,
                event_type="case.opened",
                actor_type="system",
                actor_ref="governance-engine",
                from_status=None,
                to_status=case.status,
                note="case created from governance decision",
            )
        )
        return case.id


def _message_dict(row: Message) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "external_message_id": row.external_message_id,
        "dataset_id": str(row.dataset_id) if row.dataset_id else None,
        "sender_ref": row.sender_ref,
        "server_ref": row.server_ref,
        "alliance_id": str(row.alliance_id) if row.alliance_id else None,
        "player_id": str(row.player_id) if row.player_id else None,
        "channel": row.channel,
        "language": row.language,
        "content": row.content,
        "content_hash": row.content_hash,
        "display_status": row.display_status,
        "occurred_at": row.occurred_at.isoformat(),
        "ingested_at": row.ingested_at.isoformat(),
        "is_synthetic": row.is_synthetic,
    }


def _risk_dict(row: RiskResult, categories: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "risk_result_id": str(row.id),
        "risk_score": float(row.risk_score),
        "risk_level": str(row.risk_level),
        "suggested_action": str(row.suggested_action),
        "confidence": float(row.confidence),
        "categories": categories,
        "detection_methods": list(row.detection_methods or []),
        "model_id": row.ml_model_id,
        "detected_at": row.detected_at.isoformat(),
        "evidence": dict(row.evidence or {}),
        "explanation": dict(row.explanation or {}),
    }


def _match_summary(match: Any) -> dict[str, Any]:
    policy = match.policy
    return {
        "policy_key": policy.policy_key,
        "name": policy.name,
        "version": policy.version,
        "policy_type": policy.policy_type,
        "action": policy.action,
        "priority": policy.priority,
        "emergency": policy.emergency,
        "specificity": match.specificity,
        "matched_conditions": list(match.leaves),
    }


def _evaluation_dict(row: PolicyEvaluation) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "message_id": str(row.message_id),
        "dataset_id": str(row.dataset_id) if row.dataset_id else None,
        "risk_result_id": str(row.risk_result_id) if row.risk_result_id else None,
        "policy_snapshot_hash": row.policy_snapshot_hash,
        "risk_score": float(row.risk_score),
        "risk_level": str(row.risk_level),
        "input_snapshot": dict(row.input_snapshot or {}),
        "matched_policies": list(row.matched_policies or []),
        "unmatched_policies": list(row.unmatched_policies or []),
        "matched_conditions": list(row.matched_conditions or []),
        "conflicts": list(row.conflicts or []),
        "selected_policy_id": str(row.selected_policy_id) if row.selected_policy_id else None,
        "selected_policy_version": row.selected_policy_version,
        "suggested_action": str(row.suggested_action),
        "evaluation_reason": row.evaluation_reason,
        "evaluated_at": row.evaluated_at.isoformat(),
        "is_synthetic": row.is_synthetic,
    }


def _decision_dict(row: PolicyDecision) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "message_id": str(row.message_id),
        "dataset_id": str(row.dataset_id) if row.dataset_id else None,
        "policy_id": str(row.policy_id),
        "action": str(row.action),
        "risk_score": float(row.risk_score),
        "reason_codes": list(row.reason_codes or []),
        "decided_at": row.decided_at.isoformat(),
        "risk_result_id": str(row.risk_result_id) if row.risk_result_id else None,
        "policy_evaluation_id": (
            str(row.policy_evaluation_id) if row.policy_evaluation_id else None
        ),
        "decision_key": row.decision_key,
        "decision_status": row.decision_status,
        "decision_reason": row.decision_reason,
        "confidence": float(row.confidence) if row.confidence is not None else None,
        "requires_review": row.requires_review,
        "priority": row.priority,
        "decided_by": row.decided_by,
        "explanation": dict(row.explanation or {}) if row.explanation else None,
        "is_synthetic": row.is_synthetic,
    }


def _case_dict(row: ModerationCase) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "message_id": str(row.message_id),
        "status": str(row.status),
        "priority": row.priority,
        "assignee_ref": row.assignee_ref,
        "resolution": row.resolution,
        "opened_at": row.opened_at.isoformat(),
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        "decision_id": str(row.decision_id) if row.decision_id else None,
        "risk_result_id": str(row.risk_result_id) if row.risk_result_id else None,
        "required_second_review": row.required_second_review,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        "final_category": row.final_category,
        "final_level": str(row.final_level) if row.final_level else None,
        "final_action": str(row.final_action) if row.final_action else None,
        "risk_snapshot": dict(row.risk_snapshot or {}) if row.risk_snapshot else None,
        "lock_version": row.lock_version,
        "reopened_count": row.reopened_count,
        "updated_at": row.updated_at.isoformat(),
        "is_synthetic": row.is_synthetic,
    }


def _case_summary(row: ModerationCase, message: Message, now: datetime) -> dict[str, Any]:
    snapshot = row.risk_snapshot or {}
    level = snapshot.get("risk_level") or row.final_level
    return {
        "case_id": str(row.id),
        "message_id": str(row.message_id),
        "external_message_id": message.external_message_id,
        "sender_ref": message.sender_ref,
        "server_ref": message.server_ref,
        "channel": message.channel,
        "content": message.content[:280],
        "status": str(row.status),
        "priority": row.priority,
        "assignee_ref": row.assignee_ref,
        "risk_level": str(level) if level else None,
        "risk_score": snapshot.get("risk_score"),
        "suggested_action": snapshot.get("suggested_action"),
        "final_action": str(row.final_action) if row.final_action else None,
        "required_second_review": row.required_second_review,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        "overdue": bool(row.due_at is not None and row.due_at < now),
        "opened_at": row.opened_at.isoformat(),
        "lock_version": row.lock_version,
        "reopened_count": row.reopened_count,
        "is_synthetic": row.is_synthetic,
    }


def _case_level(case: ModerationCase, message: Message) -> str | None:
    snapshot = case.risk_snapshot or {}
    return str(snapshot.get("risk_level")) if snapshot.get("risk_level") else None


def _review_dict(row: ModerationReview) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "case_id": str(row.case_id),
        "decision_id": str(row.decision_id) if row.decision_id else None,
        "reviewer_ref": row.reviewer_ref,
        "reviewer_role": row.reviewer_role,
        "action": str(row.action),
        "reason": row.reason,
        "final_category": row.final_category,
        "final_level": str(row.final_level) if row.final_level else None,
        "final_action": str(row.final_action) if row.final_action else None,
        "notes": row.notes,
        "from_status": str(row.from_status) if row.from_status else None,
        "to_status": str(row.to_status) if row.to_status else None,
        "system_action": str(row.system_action) if row.system_action else None,
        "system_category": row.system_category,
        "system_level": str(row.system_level) if row.system_level else None,
        "system_confidence": (
            float(row.system_confidence) if row.system_confidence is not None else None
        ),
        "created_at": row.created_at.isoformat(),
        "is_synthetic": row.is_synthetic,
    }


def _event_dict(row: CaseEvent) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "event_type": row.event_type,
        "actor_type": row.actor_type,
        "actor_ref": row.actor_ref,
        "from_status": str(row.from_status) if row.from_status else None,
        "to_status": str(row.to_status) if row.to_status else None,
        "note": row.note,
        "created_at": row.created_at.isoformat(),
    }


def _enforcement_dict(row: EnforcementAction) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "decision_id": str(row.decision_id),
        "case_id": str(row.case_id) if row.case_id else None,
        "idempotency_key": row.idempotency_key,
        "action_type": row.action_type,
        "target_ref": row.target_ref,
        "target_type": row.target_type,
        "server_ref": row.server_ref,
        "status": str(row.status),
        "executed_at": row.executed_at.isoformat() if row.executed_at else None,
        "duration_seconds": row.duration_seconds,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "reason": row.reason,
        "simulated": row.simulated,
        "released_at": row.released_at.isoformat() if row.released_at else None,
        "release_reason": row.release_reason,
        "details": dict(row.details or {}),
        "created_at": row.created_at.isoformat(),
        "is_synthetic": row.is_synthetic,
    }


def _player_state_dict(row: PlayerEnforcementState) -> dict[str, Any]:
    return {
        "player_ref": row.player_ref,
        "scope_ref": row.scope_ref,
        "server_ref": row.server_ref,
        "mute_until": row.mute_until.isoformat() if row.mute_until else None,
        "ban_until": row.ban_until.isoformat() if row.ban_until else None,
        "permanent_ban": row.permanent_ban,
        "warn_count": row.warn_count,
        "last_enforcement_id": (str(row.last_enforcement_id) if row.last_enforcement_id else None),
        "updated_at": row.updated_at.isoformat(),
        "is_synthetic": row.is_synthetic,
    }


def _feedback_dict(row: GovernanceFeedback) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "message_id": str(row.message_id),
        "decision_id": str(row.decision_id) if row.decision_id else None,
        "review_id": str(row.review_id) if row.review_id else None,
        "feedback_type": str(row.feedback_type),
        "difference_reason": row.difference_reason,
        "original_prediction": dict(row.original_prediction or {}),
        "original_risk": dict(row.original_risk or {}),
        "final_risk": dict(row.final_risk or {}),
        "policy_version": row.policy_version,
        "model_version": row.model_version,
        "reviewer_ref": row.reviewer_ref,
        "created_at": row.created_at.isoformat(),
        "is_synthetic": row.is_synthetic,
    }


def _outbox_dict(row: OutboxEvent) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "aggregate_type": row.aggregate_type,
        "aggregate_id": row.aggregate_id,
        "event_type": row.event_type,
        "topic": row.topic,
        "payload": dict(row.payload or {}),
        "headers": dict(row.headers or {}),
        "dedupe_key": row.dedupe_key,
        "status": str(row.status),
        "attempts": row.attempts,
        "available_at": row.available_at.isoformat(),
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat(),
    }


def _audit_dict(row: AuditEvent) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "entity_type": row.entity_type,
        "entity_id": str(row.entity_id),
        "action": row.action,
        "actor_type": row.actor_type,
        "actor_ref": row.actor_ref,
        "actor_role": row.actor_role,
        "reason": row.reason,
        "before_state": row.before_state,
        "after_state": row.after_state,
        "details": dict(row.details or {}),
        "created_at": row.created_at.isoformat(),
    }


def _audit_rows(session: Session, message_id: UUID, limit: int) -> list[dict[str, Any]]:
    decision_ids = list(
        session.scalars(select(PolicyDecision.id).where(PolicyDecision.message_id == message_id))
    )
    case_ids = list(
        session.scalars(select(ModerationCase.id).where(ModerationCase.message_id == message_id))
    )
    rows = session.scalars(
        select(AuditEvent)
        .where(
            or_(
                AuditEvent.entity_id == message_id,
                AuditEvent.entity_id.in_(decision_ids or [uuid4()]),
                AuditEvent.entity_id.in_(case_ids or [uuid4()]),
            )
        )
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
    ).all()
    return [_audit_dict(row) for row in rows]


def _audit(
    session: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    action: str,
    actor_ref: str,
    actor_role: str,
    reason: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_type="user" if actor_role != "system" else "system",
            actor_ref=actor_ref,
            actor_role=actor_role,
            reason=reason,
            before_state=before,
            after_state=after,
            details={"synthetic": True},
        )
    )


def _enqueue(session: Session, draft: OutboxDraft) -> None:
    existing = session.scalar(
        select(OutboxEvent.id).where(OutboxEvent.dedupe_key == draft.dedupe_key)
    )
    if existing is not None:
        return
    session.add(
        OutboxEvent(
            aggregate_type=str(draft.headers.get("aggregate", "governance")),
            aggregate_id=str(
                draft.payload.get("decision_id") or draft.payload.get("case_id") or ""
            ),
            event_type=draft.event_type,
            topic=draft.topic,
            payload=draft.payload,
            headers=dict(draft.headers),
            dedupe_key=draft.dedupe_key,
            available_at=datetime.now(UTC),
        )
    )


def _later(current: datetime | None, candidate: datetime) -> datetime:
    return candidate if current is None or candidate > current else current


def _policy_version(session: Session, decision: PolicyDecision) -> int | None:
    if decision.policy_evaluation_id is not None:
        evaluation = session.get(PolicyEvaluation, decision.policy_evaluation_id)
        return evaluation.selected_policy_version if evaluation is not None else None
    return None


def _require_text(value: str, name: str, max_length: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise GovernanceValidationError(
            f"{name} must be a non-empty string of at most {max_length} characters"
        )
