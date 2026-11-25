"""Deterministic, removable end-to-end demonstration.

The demo runs the *real* pipeline: every message goes through ingestion,
detection (rule + ML + fusion), policy evaluation, decision and routing. The
governance steps afterwards use the same services the Streamlit pages call.

Nothing here fabricates a result: each step reports the identifier it produced,
and a re-run either produces the same identifiers (idempotent stages) or reports
``skipped`` with the reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from claro.analytics.filters import AnalyticsFilters
from claro.analytics.strategy import StrategyReplayService
from claro.application.enforcement_service import EnforcementService
from claro.application.feedback_audit_service import FeedbackAuditService
from claro.application.message_events import RawGameMessagePayload
from claro.application.moderation_service import ModerationService
from claro.application.processing_service import ClaroProcessingService, ProcessingOutcome
from claro.data_access.repositories.governance_repository import GovernanceRepository
from claro.data_generation.demo_scenarios import (
    DEMO_ANCHOR,
    DEMO_DATASET_NAME,
    DEMO_SEED,
    SCENARIOS,
    scenario_payloads,
)

DEMO_ACTOR = "reviewer.demo"
DEMO_SENIOR = "reviewer.demo.senior"


class DemoError(RuntimeError):
    """Raised when the demo cannot proceed and the reason must be reported."""


@dataclass(slots=True)
class DemoStep:
    scenario: str
    title: str
    status: str
    detail: str
    reference: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "reference": self.reference,
        }


@dataclass(slots=True)
class DemoReport:
    dataset: str
    dataset_id: UUID
    started_at: datetime
    steps: list[DemoStep] = field(default_factory=list)
    outcomes: list[ProcessingOutcome] = field(default_factory=list)
    finished_at: datetime | None = None

    def add(self, step: DemoStep) -> None:
        self.steps.append(step)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "dataset_id": str(self.dataset_id),
            "started_at": self.started_at.isoformat(),
            "finished_at": (self.finished_at or datetime.now(UTC)).isoformat(),
            "messages": [outcome.to_dict() for outcome in self.outcomes],
            "steps": [step.to_dict() for step in self.steps],
            "summary": self.summary(),
        }

    def summary(self) -> dict[str, Any]:
        messages = len(self.outcomes)
        processed = sum(1 for item in self.outcomes if item.status == "processed")
        duplicates = sum(1 for item in self.outcomes if item.status == "duplicate")
        failed = sum(1 for item in self.outcomes if item.status in {"failed", "partial"})
        return {
            "messages": messages,
            "processed": processed,
            "duplicate": duplicates,
            "failed": failed,
            "steps": len(self.steps),
            "steps_ok": sum(1 for step in self.steps if step.status in {"ok", "existing"}),
        }


class DemoService:
    """Seed, run and remove the demonstration dataset."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        engine: Engine,
        processing: ClaroProcessingService,
        governance: GovernanceRepository,
        moderation: ModerationService | None,
        enforcement: EnforcementService | None,
        feedback: FeedbackAuditService | None,
        strategy: StrategyReplayService | None,
    ) -> None:
        self._sessions = session_factory
        self._engine = engine
        self._processing = processing
        self._governance = governance
        self._moderation = moderation
        self._enforcement = enforcement
        self._feedback = feedback
        self._strategy = strategy
        self._logger = structlog.get_logger(__name__)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def run(self) -> DemoReport:
        dataset_id = self._processing.resolve_dataset(DEMO_DATASET_NAME, seed=DEMO_SEED)
        report = DemoReport(
            dataset=DEMO_DATASET_NAME, dataset_id=dataset_id, started_at=datetime.now(UTC)
        )

        payloads = [
            RawGameMessagePayload.model_validate(item)
            for item in scenario_payloads(dataset_id=dataset_id)
        ]
        for payload in payloads:
            outcome = self._processing.process_message(payload)
            report.outcomes.append(outcome)
        report.add(
            DemoStep(
                scenario="1-7",
                title="消息接入 → 风险识别 → 策略决策",
                status="ok"
                if not any(o.status == "failed" for o in report.outcomes)
                else "partial",
                detail="; ".join(
                    f"{_scenario_title(o.external_message_id)}={o.status}/"
                    f"{(o.risk or {}).get('risk_level', '—')}/"
                    f"{(o.decision or {}).get('action', '—')}"
                    for o in report.outcomes
                ),
                reference=str(dataset_id),
            )
        )

        cases = self._open_cases()
        report.add(self._claim(cases))
        report.add(
            DemoStep(
                scenario="9",
                title="人工审核：推翻系统动作（block → mute）",
                **self._review(
                    cases,
                    index=0,
                    action="override",
                    final_action="mute",
                    final_level="high",
                    reason="演示：证据支持违规，但认为拦截过重，改为禁言",
                ),
            )
        )
        report.add(self._enforce_mute(cases))
        report.add(self._enforce_temp_ban(cases))
        report.add(self._release_mute())
        report.add(self._submit_feedback(cases))
        report.add(self._replay(dataset_id))
        report.finished_at = datetime.now(UTC)
        return report

    # ------------------------------------------------------------------
    # Governance steps
    # ------------------------------------------------------------------
    def _open_cases(self) -> list[dict[str, Any]]:
        cases: list[dict[str, Any]] = []
        for scenario in SCENARIOS:
            case = self._governance.case_for_message(scenario.message_id)
            if case is not None:
                cases.append(case)
        return cases

    def _claim(self, cases: list[dict[str, Any]]) -> DemoStep:
        if self._moderation is None or not cases:
            return DemoStep("8", "进入人工审核", "skipped", "审核服务或案例不可用")
        case = cases[0]
        if case["status"] not in {"open", "pending"}:
            return DemoStep(
                "8",
                "进入人工审核",
                "existing",
                f"案例状态 {case['status']}，已越过认领阶段",
                case["id"],
            )
        detail = self._moderation.detail(UUID(str(case["id"])))
        self._moderation.claim(
            UUID(str(case["id"])),
            reviewer_ref=DEMO_ACTOR,
            reviewer_role="moderator",
            expected_lock_version=int(detail["case"].get("lock_version") or 0),
        )
        return DemoStep(
            "8",
            "进入人工审核",
            "ok",
            "案例已认领（in_review），锁定版本递增",
            case["id"],
        )

    def _review(
        self,
        cases: list[dict[str, Any]],
        *,
        index: int,
        action: str,
        final_action: str,
        final_level: str,
        reason: str,
    ) -> dict[str, Any]:
        if self._moderation is None:
            return {"status": "skipped", "detail": "审核服务不可用", "reference": None}
        if index >= len(cases):
            return {"status": "skipped", "detail": "没有待审核案例", "reference": None}
        case = cases[index]
        if case["status"] not in {"open", "pending", "in_review"}:
            return {
                "status": "skipped",
                "detail": f"案例已处于 {case['status']}，跳过重复审核",
                "reference": case["id"],
            }
        detail = self._moderation.detail(UUID(str(case["id"])))
        lock_version = int(detail["case"].get("lock_version") or 0)
        role = "moderator"
        try:
            self._moderation.claim(
                UUID(str(case["id"])),
                reviewer_ref=DEMO_ACTOR,
                reviewer_role=role,
                expected_lock_version=lock_version,
            )
        except Exception as error:  # noqa: BLE001 - already claimed means usable state
            self._logger.info("demo_claim_skipped", case_id=case["id"], error=str(error))
        need_escalation = str(detail["case"].get("status")) == "escalated"
        result = self._moderation.submit_review(
            UUID(str(case["id"])),
            reviewer_ref=DEMO_SENIOR if need_escalation else DEMO_ACTOR,
            reviewer_role="senior_moderator" if need_escalation else role,
            action=action,
            reason=reason,
            final_action=final_action,
            final_level=final_level,
            notes="phase-06 demo",
        )
        return {
            "status": "ok",
            "detail": f"{action} → {final_action}；案例 {result.get('status', 'updated')}",
            "reference": case["id"],
        }

    def _enforce_mute(self, cases: list[dict[str, Any]]) -> DemoStep:
        if self._enforcement is None or not cases:
            return DemoStep("10", "模拟禁言", "skipped", "处置服务或案例不可用")
        decision_id = self._decision_id(cases[0])
        if decision_id is None:
            return DemoStep("10", "模拟禁言", "skipped", "案例缺少决策记录")
        scenario = self._scenario_for_message(cases[0]["message_id"])
        result = self._enforcement.simulate_enforcement(
            decision_id=decision_id,
            action="mute",
            target_ref=scenario.player_ref if scenario else "demo-player",
            reason="演示：确认违规后执行 10 分钟禁言（模拟）",
            actor_ref=DEMO_ACTOR,
            duration_seconds=600,
        )
        state = str(result.get("status"))
        return DemoStep(
            "10",
            "模拟禁言",
            "ok" if state == "executed" else "existing",
            f"mute → {state}；到期 {result.get('expires_at')}",
            str(result.get("id")),
        )

    def _enforce_temp_ban(self, cases: list[dict[str, Any]]) -> DemoStep:
        if self._enforcement is None or len(cases) < 2:
            return DemoStep("11", "模拟临时封禁", "skipped", "处置服务或第二个案例不可用")
        case = cases[1]
        review = self._review(
            cases,
            index=1,
            action="override",
            final_action="temp_ban",
            final_level="high",
            reason="演示：人工判断应升级处置，覆盖系统建议的复核动作",
        )
        decision_id = self._decision_id(case)
        if decision_id is None:
            return DemoStep("11", "模拟临时封禁", "skipped", "案例缺少决策记录")
        scenario = self._scenario_for_message(case["message_id"])
        result = self._enforcement.simulate_enforcement(
            decision_id=decision_id,
            action="temp_ban",
            target_ref=scenario.player_ref if scenario else "demo-player",
            reason="演示：审核确认后执行 30 分钟临时封禁（模拟）",
            actor_ref=DEMO_SENIOR,
            duration_seconds=1_800,
        )
        state = str(result.get("status"))
        return DemoStep(
            "11",
            "模拟临时封禁",
            "ok" if state == "executed" else "existing",
            f"审核 {review['status']}；temp_ban → {state}；到期 {result.get('expires_at')}",
            str(result.get("id")),
        )

    def _release_mute(self) -> DemoStep:
        if self._enforcement is None:
            return DemoStep("12", "解除处罚", "skipped", "处置服务不可用")
        mute = next(
            (
                item
                for item in self._enforcement.get_enforcement_history(limit=500)
                if item.get("action_type") == "mute"
                and item.get("target_ref", "").startswith("demo-player")
                and item.get("status") == "executed"
            ),
            None,
        )
        if mute is None:
            return DemoStep("12", "解除处罚", "skipped", "没有处于执行中的演示禁言")
        result = self._enforcement.release_enforcement(
            UUID(str(mute["id"])),
            actor_ref=DEMO_SENIOR,
            reason="演示：申诉通过，提前解除禁言（模拟）",
        )
        return DemoStep(
            "12",
            "解除处罚",
            "ok",
            f"release → {result.get('status')}",
            str(result.get("id")),
        )

    def _submit_feedback(self, cases: list[dict[str, Any]]) -> DemoStep:
        if self._feedback is None or not cases:
            return DemoStep("13", "反馈进入分析层", "skipped", "反馈服务或案例不可用")
        if len(cases) < 2:
            return DemoStep("13", "反馈进入分析层", "skipped", "缺少可反馈的已审核案例")
        case = cases[1]
        existing = self._governance.list_feedback(limit=500)
        if any(str(item.get("message_id")) == str(case["message_id"]) for item in existing):
            return DemoStep("13", "反馈进入分析层", "existing", "该案例已存在反馈记录")
        result = self._feedback.submit_feedback(
            message_id=UUID(str(case["message_id"])),
            decision_id=UUID(str(case["decision_id"])) if case.get("decision_id") else None,
            feedback_type="level_error",
            difference_reason="演示：系统判定等级偏低，人工升级为临时封禁",
            reviewer_ref=DEMO_SENIOR,
            final_risk={"final_action": "temp_ban"},
        )
        return DemoStep(
            "13",
            "反馈进入分析层",
            "ok",
            f"feedback={result.get('feedback_type')}",
            str(result.get("id")),
        )

    def _replay(self, dataset_id: UUID) -> DemoStep:
        if self._strategy is None:
            return DemoStep("14", "策略对比回放", "skipped", "回放服务不可用")
        existing = self._strategy.list_runs().get("runs", [])
        if any(
            str(item.get("dataset_name") or "") == DEMO_DATASET_NAME
            or str(item.get("dataset_id") or "") == str(dataset_id)
            for item in existing
        ):
            return DemoStep("14", "策略对比回放", "existing", "该演示数据集已有回放记录")
        filters = AnalyticsFilters(
            start=DEMO_ANCHOR - timedelta(days=1),
            end=DEMO_ANCHOR + timedelta(days=1),
            dataset_id=dataset_id,
            dataset_name=DEMO_DATASET_NAME,
        )
        result = self._strategy.run(
            filters,
            {
                "action_overrides": {"gov-keyword-gold-selling": "warn"},
                "baseline_label": "active",
                "candidate_label": "gold-selling→warn",
            },
            sample_limit=200,
            executed_by="demo",
        )
        candidate = result.get("candidate") or {}
        differences = result.get("differences") or {}
        metrics = candidate.get("metrics") or {}
        return DemoStep(
            "14",
            "策略对比回放",
            "ok",
            f"样本 {result.get('sample_count', 0)}；"
            f"动作变化 {differences.get('action_changes', 0)}；"
            f"候选误杀率 {metrics.get('false_positive_rate', '—')}；"
            f"低样本 {result.get('low_sample')}",
            str(result.get("run_id") or ""),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _decision_id(self, case: dict[str, Any]) -> UUID | None:
        value = case.get("decision_id")
        return UUID(str(value)) if value else None

    def _scenario_for_message(self, message_id: Any):
        return next((item for item in SCENARIOS if str(item.message_id) == str(message_id)), None)

    # ------------------------------------------------------------------
    # Status and cleanup
    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT d.id, d.name,
                           (SELECT count(*) FROM message m WHERE m.dataset_id = d.id) AS messages,
                           (SELECT count(*) FROM risk_result rr WHERE rr.dataset_id = d.id) AS risk,
                           (SELECT count(*) FROM moderation_case mc
                              JOIN message m2 ON m2.id = mc.message_id
                             WHERE m2.dataset_id = d.id) AS cases,
                           (SELECT count(*) FROM governance_feedback gf
                              JOIN message m3 ON m3.id = gf.message_id
                             WHERE m3.dataset_id = d.id) AS feedback
                    FROM dataset d WHERE d.name = :name
                    """
                    ),
                    {"name": DEMO_DATASET_NAME},
                )
                .mappings()
                .first()
            )
        if row is None:
            return {"exists": False, "dataset": DEMO_DATASET_NAME}
        return {"exists": True, **dict(row)}

    def clean(self) -> dict[str, int]:
        """Delete only records that belong to the demonstration dataset.

        Rows are addressed by the deterministic demo message ids as well as by
        the dataset id, so a partially failed run (for example an ingestion that
        never wrote a message but did write an inbox row) is still removable.
        """
        dataset_id = self._dataset_id()
        message_ids = [str(item.message_id) for item in SCENARIOS]
        deleted: dict[str, int] = {}
        with self._sessions() as session:
            decision_ids = [
                str(row[0])
                for row in session.execute(
                    text("SELECT id FROM policy_decision WHERE message_id = ANY(:ids)"),
                    {"ids": message_ids},
                )
            ]
            replay_runs = [
                str(row[0])
                for row in session.execute(
                    text("SELECT run_id FROM analytics_replay_run WHERE dataset_name = :name"),
                    {"name": DEMO_DATASET_NAME},
                )
            ]
            statements: list[tuple[str, str, dict[str, Any]]] = [
                (
                    "audit_event",
                    "DELETE FROM audit_event WHERE entity_id = ANY(:ids)",
                    {"ids": [*message_ids, *decision_ids]},
                ),
                (
                    "analytics_replay_case",
                    "DELETE FROM analytics_replay_case WHERE run_id = ANY(:runs)",
                    {"runs": replay_runs},
                ),
                (
                    "analytics_replay_run",
                    "DELETE FROM analytics_replay_run WHERE dataset_name = :name",
                    {"name": DEMO_DATASET_NAME},
                ),
                (
                    "player_enforcement_state",
                    "DELETE FROM player_enforcement_state WHERE player_ref = ANY(:players)",
                    {"players": [item.player_ref for item in SCENARIOS]},
                ),
                (
                    "inbox_event",
                    "DELETE FROM inbox_event WHERE event_id = ANY(:ids)",
                    {"ids": message_ids},
                ),
                ("message", "DELETE FROM message WHERE id = ANY(:ids)", {"ids": message_ids}),
            ]
            if dataset_id is not None:
                statements.extend(
                    [
                        (
                            "player",
                            "DELETE FROM player WHERE dataset_id = :dataset",
                            {"dataset": dataset_id},
                        ),
                        (
                            "server",
                            "DELETE FROM server WHERE dataset_id = :dataset",
                            {"dataset": dataset_id},
                        ),
                        (
                            "alliance",
                            "DELETE FROM alliance WHERE dataset_id = :dataset",
                            {"dataset": dataset_id},
                        ),
                        (
                            "dataset",
                            "DELETE FROM dataset WHERE id = :dataset",
                            {"dataset": dataset_id},
                        ),
                    ]
                )
            for name, statement, params in statements:
                if "ids" in params and not params["ids"]:
                    deleted[name] = 0
                    continue
                if "runs" in params and not params["runs"]:
                    deleted[name] = 0
                    continue
                result = session.execute(text(statement), params)
                deleted[name] = int(result.rowcount or 0)
            session.commit()
        self._logger.info("demo_dataset_cleaned", dataset=str(dataset_id), deleted=deleted)
        return deleted

    def _dataset_id(self) -> UUID | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text("SELECT id FROM dataset WHERE name = :name"), {"name": DEMO_DATASET_NAME}
            ).first()
        return row[0] if row else None


def _scenario_title(external_message_id: str) -> str:
    scenario = next(
        (item for item in SCENARIOS if item.external_message_id == external_message_id), None
    )
    return scenario.key if scenario else external_message_id
