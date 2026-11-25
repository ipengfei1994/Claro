from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from claro.data_access.repositories.governance_repository import (
    GovernanceNotFoundError,
    GovernanceRepository,
    GovernanceValidationError,
)
from claro.domain.enums import FeedbackType

#: Feedback kinds that describe a discrepancy between the machine judgement and
#: the human judgement. They feed the error-analysis closed loop.
ERROR_FEEDBACK_TYPES: frozenset[str] = frozenset(
    {
        FeedbackType.FALSE_POSITIVE.value,
        FeedbackType.FALSE_NEGATIVE.value,
        FeedbackType.CATEGORY_ERROR.value,
        FeedbackType.LEVEL_ERROR.value,
        FeedbackType.ACTION_INAPPROPRIATE.value,
        FeedbackType.INSUFFICIENT_EVIDENCE.value,
    }
)


class FeedbackAuditService:
    """Human feedback capture and the append-only audit trail.

    Feedback keeps the original machine prediction next to the human outcome so
    that error analysis can compare them later. It is stored, queryed and
    summarised here only; it is never used to retrain a model on the fly. The
    audit trail is append-only: there is no update or delete path.
    """

    def __init__(self, repository: GovernanceRepository) -> None:
        self._repository = repository
        self._logger = structlog.get_logger(__name__)

    # Feedback ---------------------------------------------------------------
    def submit_feedback(
        self,
        *,
        message_id: UUID,
        feedback_type: str,
        difference_reason: str,
        reviewer_ref: str,
        decision_id: UUID | None = None,
        review_id: UUID | None = None,
        final_risk: dict[str, Any] | None = None,
        is_synthetic: bool = True,
    ) -> dict[str, Any]:
        if feedback_type not in {item.value for item in FeedbackType}:
            raise GovernanceValidationError(f"unknown feedback type: {feedback_type}")
        result = self._repository.create_feedback(
            message_id=message_id,
            decision_id=decision_id,
            review_id=review_id,
            feedback_type=feedback_type,
            difference_reason=difference_reason,
            final_risk=final_risk or {},
            reviewer_ref=reviewer_ref,
            is_synthetic=is_synthetic,
        )
        return {**result, "is_error_case": feedback_type in ERROR_FEEDBACK_TYPES}

    def get_feedback(self, *, limit: int = 200) -> list[dict[str, Any]]:
        return self._repository.list_feedback(limit=limit)

    def feedback_stats(self) -> dict[str, Any]:
        return self._repository.feedback_stats()

    def get_error_cases(
        self, *, feedback_type: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Return false positives, false negatives and other discrepancy cases."""
        cases = [
            item
            for item in self._repository.list_feedback(limit=max(limit, 1))
            if item["feedback_type"] in ERROR_FEEDBACK_TYPES
        ]
        if feedback_type is not None:
            if feedback_type not in ERROR_FEEDBACK_TYPES:
                raise GovernanceValidationError(f"'{feedback_type}' is not an error feedback type")
            cases = [item for item in cases if item["feedback_type"] == feedback_type]
        return cases[:limit]

    def error_breakdown(self) -> dict[str, int]:
        stats = self._repository.feedback_stats()
        by_type = stats.get("by_type", {})
        return {kind: int(by_type.get(kind, 0)) for kind in sorted(ERROR_FEEDBACK_TYPES)}

    # Audit ------------------------------------------------------------------
    def get_audit_logs(
        self,
        *,
        entity_type: str | None = None,
        action: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        return self._repository.list_audit(entity_type=entity_type, action=action, limit=limit)

    def get_resource_audit(
        self, entity_type: str, entity_id: UUID, *, limit: int = 200
    ) -> list[dict[str, Any]]:
        rows = self._repository.list_audit(entity_type=entity_type, limit=1_000)
        return [row for row in rows if str(row["entity_id"]) == str(entity_id)][:limit]

    def trace(self, message_id: UUID) -> dict[str, Any]:
        result = self._repository.governance_trace(message_id)
        if not result.get("message"):
            raise GovernanceNotFoundError(f"message not found: {message_id}")
        return result
