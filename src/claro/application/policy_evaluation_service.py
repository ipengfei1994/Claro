from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from claro.application.governance_cache import GovernanceCacheService
from claro.application.policy_service import PolicyService
from claro.data_access.repositories.governance_repository import (
    GovernanceNotFoundError,
    GovernanceRepository,
)
from claro.governance.policy import PolicyContext, evaluate_policies


class PolicyEvaluationService:
    """Evaluate active governance policies against one message's risk result.

    The service has no side effects beyond persisting the immutable evaluation
    record and incrementing policy hit counters. Evaluation is deterministic:
    the same risk result and the same policy snapshot always produce the same
    evaluation row, so repeated risk events remain idempotent.
    """

    def __init__(
        self,
        repository: GovernanceRepository,
        policy_service: PolicyService,
        *,
        cache: GovernanceCacheService | None = None,
        default_actions: Mapping[str, str] | None = None,
        rate_window_seconds: int = 60,
    ) -> None:
        if rate_window_seconds < 1:
            raise ValueError("rate_window_seconds must be positive")
        self._repository = repository
        self._policy_service = policy_service
        self._cache = cache
        self._default_actions = dict(default_actions) if default_actions else None
        self._rate_window = rate_window_seconds
        self._logger = structlog.get_logger(__name__)

    def evaluate_message(
        self, message_id: UUID, *, now: datetime | None = None
    ) -> dict[str, Any]:
        moment = now or datetime.now(UTC)
        self._policy_service.ensure_default_policy()
        context_data = self._repository.message_context(message_id)
        context: PolicyContext = context_data["policy_context"]
        rate_count = self._sender_rate(context.sender_ref, moment)
        if rate_count != context.rate_count:
            context = replace(context, rate_count=rate_count)
        policies = self._policy_service.active_snapshots(now=moment)
        default_policy = self._policy_service.get_default_snapshot()
        outcome = evaluate_policies(
            context,
            policies,
            default_policy=default_policy,
            now=moment,
            default_actions=self._default_actions,
        )
        message = context_data["message"]
        stored = self._repository.save_evaluation(
            context=context,
            outcome=outcome,
            risk_result_id=UUID(str(context_data["risk"]["risk_result_id"])),
            dataset_id=UUID(str(message["dataset_id"])) if message["dataset_id"] else None,
            is_synthetic=bool(message["is_synthetic"]),
        )
        if stored.get("created", False):
            self._policy_service.increment_hits(
                [item.policy.policy_id for item in outcome.matched]
            )
        return {
            **stored,
            "matched": [_match_summary(item) for item in outcome.matched],
            "unmatched_count": len(outcome.unmatched),
            "selected_is_default": outcome.selected_is_default,
            "default_action_applied": outcome.selected_is_default,
        }

    def explain_evaluation(self, evaluation_id: UUID) -> dict[str, Any]:
        row = self._repository.get_evaluation(evaluation_id)
        if row is None:
            raise GovernanceNotFoundError(f"evaluation not found: {evaluation_id}")
        conflicts = row["conflicts"]
        return {
            "evaluation": row,
            "selected_policy_id": row["selected_policy_id"],
            "selected_policy_version": row["selected_policy_version"],
            "suggested_action": row["suggested_action"],
            "evaluation_reason": row["evaluation_reason"],
            "matched_policies": row["matched_policies"],
            "unmatched_policy_count": len(row["unmatched_policies"]),
            "matched_conditions": row["matched_conditions"],
            "conflicts": conflicts,
            "has_conflicts": bool(conflicts),
        }

    def latest(self, message_id: UUID) -> dict[str, Any] | None:
        return self._repository.latest_evaluation(message_id)

    def list_evaluations(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._repository.list_evaluations(limit)

    def _sender_rate(self, sender_ref: str, moment: datetime) -> int:
        if self._cache is not None:
            return self._cache.sender_message_rate(sender_ref, now=moment)
        return self._repository.sender_message_rate(
            sender_ref, window_seconds=self._rate_window, now=moment
        )


def _match_summary(match: Any) -> dict[str, Any]:
    policy = match.policy
    return {
        "policy_id": str(policy.policy_id),
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
