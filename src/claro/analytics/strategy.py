"""Strategy evaluation and isolated historical replay.

A replay reads immutable historical messages and policy snapshots, evaluates
two policy sets in memory, and writes only to the analytics replay tables. It
never calls an enforcement service, publishes an event, or modifies a formal
decision.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import sessionmaker

from claro.analytics.data_access import AnalyticsRepository
from claro.analytics.definitions import (
    KPI_DEFINITION_VERSION,
    MIN_POLICY_DECISIONS,
    MIN_REPLAY_SAMPLES,
    TIER_LABELS,
    DataSourceTier,
)
from claro.analytics.filters import AnalyticsFilters
from claro.analytics.metrics import (
    action_diff,
    as_float,
    as_int,
    classification_metrics,
    predicted_positive,
    ratio,
    truth_positive,
)
from claro.analytics.services import jsonable
from claro.data_access.database import session_scope
from claro.data_access.models import AnalyticsReplayCase, AnalyticsReplayRun
from claro.data_access.repositories.policy_repository import PolicyRepository
from claro.governance.policy import (
    PolicyContext,
    PolicySnapshot,
    evaluate_policies,
)


class StrategyReplayError(ValueError):
    """Raised when replay parameters are invalid."""


class StrategyReplayService:
    """Evaluate candidate policy sets against unchanged historical messages."""

    def __init__(
        self,
        repository: AnalyticsRepository,
        policy_repository: PolicyRepository,
        session_factory: sessionmaker,
    ) -> None:
        self._repository = repository
        self._policies = policy_repository
        self._sessions = session_factory

    def _envelope(self, filters: AnalyticsFilters) -> dict[str, Any]:
        return {
            "definition": {"version": KPI_DEFINITION_VERSION},
            "data_source_tier": DataSourceTier.DERIVED.value,
            "data_source_label": TIER_LABELS[DataSourceTier.DERIVED],
            "filters": filters.summary(),
            "generated_at": datetime.now(UTC).isoformat(),
            "simulation": True,
            "synthetic_notice": "回放输入为合成数据；结果不是线上干预效果。",
        }

    # ------------------------------------------------------------------
    # Snapshot construction
    # ------------------------------------------------------------------
    def _version_snapshot(self, policy_id: UUID, policy_key: str, version: int) -> PolicySnapshot:
        versions = self._policies.versions(policy_id)
        match = next((item for item in versions if as_int(item.get("version")) == version), None)
        if match is None:
            raise StrategyReplayError(
                f"policy {policy_key} has no version {version}"
            )
        return PolicySnapshot(
            policy_id=policy_id,
            policy_key=policy_key,
            name=str(match["name"]),
            description=str(match["description"]),
            policy_type=str(match["policy_type"]),
            target_scope=dict(match["target_scope"]),
            conditions=dict(match["conditions"]),
            action=str(match["action"]),
            priority=as_int(match["priority"]),
            emergency=bool(match["emergency"]),
            enabled=bool(match["enabled"]),
            version=as_int(match["version"]),
            effective_from=datetime.fromisoformat(str(match["effective_from"])),
            effective_until=(
                datetime.fromisoformat(str(match["effective_until"]))
                if match.get("effective_until")
                else None
            ),
            created_by=str(match["created_by"]),
            is_synthetic=True,
        )

    def _candidate_snapshots(
        self,
        baseline: list[PolicySnapshot],
        candidate: dict[str, Any],
    ) -> list[PolicySnapshot]:
        action_overrides = dict(candidate.get("action_overrides") or {})
        priority_overrides = dict(candidate.get("priority_overrides") or {})
        version_overrides = dict(candidate.get("version_overrides") or {})
        disabled = set(candidate.get("disabled_policies") or [])
        result: list[PolicySnapshot] = []
        for snapshot in baseline:
            if snapshot.policy_key in disabled:
                continue
            updated = snapshot
            if snapshot.policy_key in version_overrides:
                updated = self._version_snapshot(
                    snapshot.policy_id,
                    snapshot.policy_key,
                    as_int(version_overrides[snapshot.policy_key]),
                )
            if snapshot.policy_key in action_overrides:
                updated = replace(updated, action=str(action_overrides[snapshot.policy_key]))
            if snapshot.policy_key in priority_overrides:
                updated = replace(
                    updated, priority=as_int(priority_overrides[snapshot.policy_key])
                )
            result.append(updated)
        return result

    # ------------------------------------------------------------------
    # Replay execution
    # ------------------------------------------------------------------
    def run(
        self,
        filters: AnalyticsFilters,
        candidate: dict[str, Any] | None = None,
        *,
        sample_limit: int = 500,
        executed_by: str = "analytics",
    ) -> dict[str, Any]:
        """Run one isolated replay and persist its metadata and per-message diff."""
        if sample_limit < 1 or sample_limit > 5000:
            raise StrategyReplayError("sample_limit must be between 1 and 5000")
        candidate = candidate or {}
        inputs = self._repository.replay_input(filters, sample_limit)
        if not inputs:
            raise StrategyReplayError("no messages match the replay filters")
        dataset_id = filters.dataset_id
        # Policy snapshots were created on 2026-11-25 while message history
        # starts 2026-01-01. Use the evaluation moment for policy effectiveness
        # and record it explicitly; this is a same-input, two-policy replay,
        # not a point-in-time historical policy reconstruction.
        now = datetime.now(UTC)
        baseline = self._policies.active_snapshots(now=now, dataset_id=dataset_id)
        default_policy = self._policies.default_policy()
        candidate_policies = self._candidate_snapshots(baseline, candidate)
        baseline_label = str(candidate.get("baseline_label") or "active@window-end")
        candidate_label = str(candidate.get("candidate_label") or "candidate")

        cases: list[dict[str, Any]] = []
        baseline_policy_stats: dict[str, dict[str, Any]] = {}
        candidate_policy_stats: dict[str, dict[str, Any]] = {}
        for row in inputs:
            category = str(row.get("category") or "other")
            score = float(as_float(row.get("risk_score")) or 0.0)
            confidence = float(as_float(row.get("confidence")) or 0.0)
            severity = str(row.get("severity") or "normal")
            context = PolicyContext(
                message_id=row["message_id"],
                content=str(row.get("content") or ""),
                content_hash=str(row["content_hash"]),
                channel=str(row["channel"]),
                language=str(row["language"]),
                sender_ref=str(row["sender_ref"]),
                server_ref=row.get("server_ref"),
                alliance_id=row.get("alliance_id"),
                risk_score=score,
                risk_level=severity,
                confidence=confidence,
                categories=(category,),
                category_scores={category: score},
                rate_count=0,
                occurred_at=None,
            )
            baseline_outcome = evaluate_policies(
                context, baseline, default_policy=default_policy, now=now
            )
            candidate_outcome = evaluate_policies(
                context, candidate_policies, default_policy=default_policy, now=now
            )
            b_hit = not baseline_outcome.selected_is_default
            c_hit = not candidate_outcome.selected_is_default
            truth = truth_positive(row.get("truth_label"))
            b_pred = predicted_positive(baseline_outcome.action)
            c_pred = predicted_positive(candidate_outcome.action)
            if b_hit != c_hit:
                diff_type = "added_hit" if c_hit else "removed_hit"
            else:
                diff_type = action_diff(baseline_outcome.action, candidate_outcome.action)
            # Per-policy attribution: a policy that matched a message is held
            # responsible for that message, so its own precision/recall can be
            # measured separately from the aggregate outcome.
            for match in baseline_outcome.matched:
                key = match.policy.policy_key
                bucket = baseline_policy_stats.setdefault(
                    key,
                    {
                        "policy_key": key,
                        "hit_messages": 0,
                        "enforcement_hits": 0,
                        "review_hits": 0,
                        "true_positives": 0,
                        "false_positives": 0,
                        "review_true_positives": 0,
                        "review_false_positives": 0,
                    },
                )
                bucket["hit_messages"] += 1
                action = match.policy.action
                if action == "review":
                    bucket["review_hits"] += 1
                    if truth:
                        bucket["review_true_positives"] += 1
                    else:
                        bucket["review_false_positives"] += 1
                elif action != "allow":
                    bucket["enforcement_hits"] += 1
                    if truth:
                        bucket["true_positives"] += 1
                    else:
                        bucket["false_positives"] += 1
            for match in candidate_outcome.matched:
                key = match.policy.policy_key
                bucket = candidate_policy_stats.setdefault(
                    key,
                    {
                        "policy_key": key,
                        "hit_messages": 0,
                        "enforcement_hits": 0,
                        "review_hits": 0,
                        "true_positives": 0,
                        "false_positives": 0,
                        "review_true_positives": 0,
                        "review_false_positives": 0,
                    },
                )
                bucket["hit_messages"] += 1
                action = match.policy.action
                if action == "review":
                    bucket["review_hits"] += 1
                    if truth:
                        bucket["review_true_positives"] += 1
                    else:
                        bucket["review_false_positives"] += 1
                elif action != "allow":
                    bucket["enforcement_hits"] += 1
                    if truth:
                        bucket["true_positives"] += 1
                    else:
                        bucket["false_positives"] += 1
            cases.append(
                {
                    "message_id": row["message_id"],
                    "baseline_hit": b_hit,
                    "candidate_hit": c_hit,
                    "baseline_action": baseline_outcome.action,
                    "candidate_action": candidate_outcome.action,
                    "baseline_policy_key": (
                        baseline_outcome.selected_policy.policy_key
                        if baseline_outcome.selected_policy
                        else None
                    ),
                    "candidate_policy_key": (
                        candidate_outcome.selected_policy.policy_key
                        if candidate_outcome.selected_policy
                        else None
                    ),
                    "diff_type": diff_type,
                    "truth_label": row.get("truth_label"),
                    "baseline_fp": bool(b_pred and not truth),
                    "baseline_fn": bool(not b_pred and truth),
                    "candidate_fp": bool(c_pred and not truth),
                    "candidate_fn": bool(not c_pred and truth),
                    "risk_score": score,
                    "input_snapshot": {
                        "content_hash": str(row["content_hash"]),
                        "category": category,
                        "severity": severity,
                        "risk_score": score,
                        "confidence": confidence,
                        "truth_label": row.get("truth_label"),
                        "has_risk_event": bool(row.get("has_risk_event")),
                        "rate_count": 0,
                    },
                }
            )

        run_id = uuid4()
        with_risk_event = sum(1 for case in cases if case["input_snapshot"]["has_risk_event"])
        truth_positives = sum(1 for case in cases if truth_positive(case["truth_label"]))
        truth_negatives = len(cases) - truth_positives
        parameters = {
            "candidate": candidate,
            "sample_limit": sample_limit,
            "baseline_policy_count": len(baseline),
            "candidate_policy_count": len(candidate_policies),
            "evaluation_now": now.isoformat(),
            "policy_effectiveness_basis": "evaluation time, not message time",
            "rate_count": 0,
            "sample_pool": {
                "definition": "all scoped labelled messages, clean messages included",
                "with_risk_event": with_risk_event,
                "without_risk_event": len(cases) - with_risk_event,
                "truth_positives": truth_positives,
                "truth_negatives": truth_negatives,
            },
            "baseline_policy_effectiveness": list(baseline_policy_stats.values()),
            "candidate_policy_effectiveness": list(candidate_policy_stats.values()),
        }
        with session_scope(self._sessions) as session:
            session.add(
                AnalyticsReplayRun(
                    run_id=run_id,

                    created_at=datetime.now(UTC),
                    dataset_name=filters.dataset_name or "dataset_id=" + str(dataset_id),
                    window_start=filters.start,
                    window_end=filters.end,
                    baseline_label=baseline_label,
                    candidate_label=candidate_label,
                    sample_count=len(cases),
                    definition_version=KPI_DEFINITION_VERSION,
                    parameters=parameters,
                    simulation=True,
                    executed_by=executed_by,
                )
            )
            session.flush()  # parent row must exist before bulk child insert
            for case in cases:
                session.add(AnalyticsReplayCase(run_id=run_id, **case))
        return self.compare(run_id)["runs"][0]

    # ------------------------------------------------------------------
    # Reporting on stored replays
    # ------------------------------------------------------------------
    def _policy_effectiveness(
        self,
        parameters: Any,
        key: str,
        case_count: int,
    ) -> list[dict[str, Any]]:
        """Turn stored per-policy counters into interpretable quality metrics.

        A policy that matched many messages is not necessarily a good policy.
        Each entry therefore keeps detection quality (precision/recall), the
        false-positive and false-negative risk and the manual review load
        side by side, so a ranking can never be driven by hit count alone.

        Recall and false-negative risk are only meaningful for policies that
        actually act on risk: a policy configured to allow everything never
        performs enforcement, so it has no detection performance to report.
        Such policies are marked explicitly instead of being shown as a
        perfect 0% recall.
        """
        rows = (parameters or {}).get(key) or []
        if not isinstance(rows, list):
            return []
        truth_positives = as_int(
            ((parameters or {}).get("sample_pool") or {}).get("truth_positives")
        )
        truth_negatives = as_int(
            ((parameters or {}).get("sample_pool") or {}).get("truth_negatives")
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            hits = as_int(row.get("hit_messages"))
            tp = as_int(row.get("true_positives"))
            fp = as_int(row.get("false_positives"))
            review_tp = as_int(row.get("review_true_positives"))
            review_fp = as_int(row.get("review_false_positives"))
            enforcement_hits = as_int(row.get("enforcement_hits"))
            review_hits = as_int(row.get("review_hits"))
            acts_on_risk = enforcement_hits + review_hits > 0
            if acts_on_risk:
                # A matched message routed to a moderator was still detected,
                # so review hits count as true positives. The review load is
                # reported on its own axis.
                detected_tp = tp + review_tp
                detected_fp = fp + review_fp
                metrics = classification_metrics(
                    {
                        "tp": detected_tp,
                        "fp": detected_fp,
                        "fn": max(truth_positives - detected_tp, 0),
                        "tn": max(truth_negatives - detected_fp, 0),
                    }
                )
            else:
                # Never acts: no detection performance exists.
                metrics = {
                    "precision": None,
                    "recall": None,
                    "f1": None,
                    "false_positive_rate": None,
                    "false_negative_rate": None,
                }
            result.append(
                {
                    "policy_key": str(row.get("policy_key")),
                    "hit_messages": hits,
                    "enforcement_hits": enforcement_hits,
                    "review_hits": review_hits,
                    "true_positives": tp,
                    "false_positives": fp,
                    "acts_on_risk": acts_on_risk,
                    "precision": metrics["precision"],
                    "recall": metrics["recall"],
                    "f1": metrics["f1"],
                    "false_positive_rate": metrics["false_positive_rate"],
                    "false_negative_rate": metrics["false_negative_rate"],
                    "manual_review_rate": ratio(review_hits, enforcement_hits + review_hits),
                    "sample_size": case_count,
                    "low_sample": hits < MIN_POLICY_DECISIONS,
                }
            )
        result.sort(key=lambda item: (-item["hit_messages"], item["policy_key"]))
        return result

    def list_runs(self) -> dict[str, Any]:
        runs = [jsonable(row) for row in self._repository.replay_runs()]
        return {"runs": runs, "simulation": True}

    def compare(self, run_id: UUID | None = None) -> dict[str, Any]:
        summaries = self._repository.replay_summary(run_id=run_id)
        runs: list[dict[str, Any]] = []
        for row in summaries:
            case_count = as_int(row["case_count"])
            b_hits = as_int(row["baseline_hits"])
            c_hits = as_int(row["candidate_hits"])
            b_fp, b_fn = as_int(row["baseline_fp"]), as_int(row["baseline_fn"])
            c_fp, c_fn = as_int(row["candidate_fp"]), as_int(row["candidate_fn"])
            # The confusion matrix is rebuilt from the per-case truth/prediction
            # flags, never from hit counts. A policy that matched a message is
            # not the same thing as a message the system decided to act on, so
            # mixing the two would silently corrupt the false-positive rate.
            b_truth_pos = as_int(
                ((row.get("parameters") or {}).get("sample_pool") or {}).get("truth_positives")
            )
            b_truth_neg = case_count - b_truth_pos
            c_truth_pos = b_truth_pos
            c_truth_neg = b_truth_neg
            baseline_metrics = classification_metrics(
                {
                    "tp": max(b_truth_pos - b_fn, 0),
                    "fp": b_fp,
                    "fn": b_fn,
                    "tn": max(b_truth_neg - b_fp, 0),
                }
            )
            candidate_metrics = classification_metrics(
                {
                    "tp": max(c_truth_pos - c_fn, 0),
                    "fp": c_fp,
                    "fn": c_fn,
                    "tn": max(c_truth_neg - c_fp, 0),
                }
            )
            baseline_policies = self._policy_effectiveness(
                row.get("parameters"), "baseline_policy_effectiveness", case_count
            )
            candidate_policies = self._policy_effectiveness(
                row.get("parameters"), "candidate_policy_effectiveness", case_count
            )
            runs.append(
                {
                    "run_id": str(row["run_id"]),
                    "created_at": jsonable(row["created_at"]),
                    "sample_count": case_count,
                    "baseline_label": row["baseline_label"],
                    "candidate_label": row["candidate_label"],
                    "sample_pool": (row.get("parameters") or {}).get("sample_pool", {}),
                    "baseline": {
                        "hits": b_hits,
                        "hit_rate": ratio(b_hits, case_count),
                        "review_actions": as_int(row["baseline_reviews"]),
                        "metrics": baseline_metrics,
                        "policy_effectiveness": baseline_policies,
                    },
                    "candidate": {
                        "hits": c_hits,
                        "hit_rate": ratio(c_hits, case_count),
                        "review_actions": as_int(row["candidate_reviews"]),
                        "metrics": candidate_metrics,
                        "policy_effectiveness": candidate_policies,
                    },
                    "differences": {
                        "added_hits": as_int(row["added_hits"]),
                        "removed_hits": as_int(row["removed_hits"]),
                        "action_changes": as_int(row["action_changes"]),
                        "review_load_delta": as_int(row["candidate_reviews"])
                        - as_int(row["baseline_reviews"]),
                        "false_positive_delta": c_fp - b_fp,
                        "false_negative_delta": c_fn - b_fn,
                    },
                    "low_sample": case_count < MIN_REPLAY_SAMPLES,
                    "simulation": True,
                }
            )
        cases = []
        if run_id is not None:
            cases = [jsonable(row) for row in self._repository.replay_cases(run_id)]
        result = {
            "runs": runs,
            "cases": cases,
            "simulation": True,
            "definition_version": KPI_DEFINITION_VERSION,
            "notes": [
                "离线回放使用历史消息快照，不触发真实处置，不修改正式决策。",
                "样本池包含窗口内全部已标注消息，含无风险事件的正常消息；"
                "因此真负例存在，误杀率可被计算。",
                "Precision/Recall 使用合成 message_label 作为 ground truth，boundary 计为负例。",
                "rate_count 固定为 0，限流类策略的回放不等同于线上实时行为。",
                "策略生效判断使用回放执行时刻（策略创建于消息历史之后），"
                "不是消息发生时刻的历史策略重建。",
                f"样本数低于 {MIN_REPLAY_SAMPLES} 时仅作为探索性结果。",
                "回放指标衡量候选策略相对基线的变化，不等于线上干预效果。",
            ],
        }
        return jsonable(result)
