"""Unified end-to-end processing for a single message.

Phase 01–05 exposed the pipeline as three independent stages driven by separate
CLI commands and Kafka consumers. That is the right production shape, but it
left no single place where "this message went through the whole platform" could
be observed, re-run or demonstrated.

:class:`ClaroProcessingService` is that entry point. It does not re-implement
any business rule: it composes the existing services in the same order the
consumers use, records a per-stage result, and reports honestly what succeeded.

Stage contract:

    validate → ingest → detect → publish → governance (evaluate/decide/enforce)

* ``ingest`` is idempotent through ``inbox_event``.
* ``detect`` is idempotent through the unique ``risk_result.message_id``.
* ``governance`` is idempotent through the pipeline's deterministic evaluation
  and decision keys.
* A stage failure never reports overall success: the outcome becomes ``partial``
  (earlier state committed, later stages ran) or ``failed`` (nothing committed).
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID

import structlog
from sqlalchemy.orm import Session, sessionmaker

from claro.application.events import EventEnvelope
from claro.application.governance_pipeline_service import GovernancePipelineService
from claro.application.message_events import RAW_GAME_MESSAGE_EVENT, RawGameMessagePayload
from claro.application.message_processing import ConsumedMessage
from claro.application.risk_events import RiskAssessedPayload
from claro.application.risk_service import RiskService, RiskServiceError
from claro.data_access.repositories.governance_repository import GovernanceRepository
from claro.data_access.repositories.kafka_repository import (
    IngestionResult,
    ensure_dataset,
    event_payload_hash,
    persist_raw_message,
)

StageStatus = Literal["ok", "duplicate", "skipped", "failed"]
OutcomeStatus = Literal["processed", "duplicate", "partial", "failed"]

DIRECT_TRANSPORT = "direct"
DIRECT_TOPIC_PREFIX = "claro.direct.v1"
SUPPORTED_TRANSPORTS = frozenset({"direct", "kafka"})


class EventPublisher(Protocol):
    def publish(
        self,
        topic: str,
        event: EventEnvelope,
        headers: Mapping[str, str] | None = None,
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class StageResult:
    """One observable step of the pipeline."""

    name: str
    status: StageStatus
    elapsed_ms: float
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.name,
            "status": self.status,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ProcessingOutcome:
    """Structured result of processing one message."""

    message_id: UUID
    external_message_id: str
    trace_id: str
    status: OutcomeStatus
    stages: tuple[StageResult, ...]
    risk: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    case_id: str | None = None
    enforcement_id: str | None = None
    error: str | None = None
    dataset_name: str | None = None
    total_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": str(self.message_id),
            "external_message_id": self.external_message_id,
            "trace_id": self.trace_id,
            "status": self.status,
            "total_ms": round(self.total_ms, 2),
            "dataset_name": self.dataset_name,
            "stages": [stage.to_dict() for stage in self.stages],
            "risk": _summarise_risk(self.risk),
            "decision": _summarise_decision(self.decision),
            "case_id": self.case_id,
            "enforcement_id": self.enforcement_id,
            "error": self.error,
        }

    def stage(self, name: str) -> StageResult | None:
        return next((item for item in self.stages if item.name == name), None)


class _StageLog:
    """Collects :class:`StageResult` entries as the pipeline advances."""

    def __init__(self) -> None:
        self.entries: list[StageResult] = []

    def run(self, name: str) -> _Stage:
        return _Stage(self, name)


class _Stage:
    """Context manager that records one stage, including failures."""

    def __init__(self, log: _StageLog, name: str) -> None:
        self._log = log
        self._name = name
        self._started = 0.0
        self.status: StageStatus = "ok"
        self.detail: str | None = None

    def __enter__(self) -> _Stage:
        self._started = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, traceback) -> Literal[False]:
        elapsed = (time.perf_counter() - self._started) * 1000
        if exc is not None:
            self.status = "failed"
            self.detail = f"{type(exc).__name__}: {exc}"
        self._log.entries.append(StageResult(self._name, self.status, elapsed, self.detail))
        return False


class ClaroProcessingService:
    """Compose ingestion, detection and governance for one message."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        risk_service: RiskService,
        governance_pipeline: GovernancePipelineService,
        governance_repository: GovernanceRepository,
        risk_topic: str,
        publisher: EventPublisher | None = None,
        processed_topic: str = "game.messages.processed",
    ) -> None:
        self._sessions = session_factory
        self._risk = risk_service
        self._governance = governance_pipeline
        self._repository = governance_repository
        self._risk_topic = risk_topic
        self._publisher = publisher
        self._processed_topic = processed_topic
        self._logger = structlog.get_logger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def resolve_dataset(self, name: str, *, seed: int, is_synthetic: bool = True) -> UUID:
        """Return a stable dataset id for ``name``, creating it when absent."""
        return ensure_dataset(
            self._sessions, name=name, seed=seed, is_synthetic=is_synthetic, source="direct"
        )

    def process_message(
        self,
        payload: RawGameMessagePayload,
        *,
        publish: bool = True,
        transport: str = DIRECT_TRANSPORT,
    ) -> ProcessingOutcome:
        """Run the full pipeline for one validated raw message payload."""
        started = time.perf_counter()
        log = _StageLog()
        error: str | None = None

        if transport not in SUPPORTED_TRANSPORTS:
            log.entries.append(
                StageResult("validate", "failed", 0.0, f"unsupported transport: {transport}")
            )
            return self._finish(log, payload, started, None, None, None, None, "invalid transport")

        log.entries.append(
            StageResult("validate", "ok", 0.0, f"{transport}:{payload.dataset_name}")
        )

        try:
            with log.run("ingest") as stage:
                ingestion = self._ingest(payload, transport=transport)
                stage.status = "duplicate" if ingestion.status == "duplicate" else "ok"
                stage.detail = f"message_status={ingestion.message_status}"
        except Exception as exc:  # noqa: BLE001 - reported in the outcome
            self._logger.warning(
                "claro_processing_ingest_failed",
                message_id=str(payload.message_id),
                error=str(exc),
            )
            return self._finish(
                log, payload, started, None, None, None, None, f"ingest failed: {exc}"
            )

        risk_summary: dict[str, Any] | None = None
        try:
            with log.run("detect") as stage:
                record = self._risk.detect(payload.message_id)
                risk_summary = record.stored.to_dict()
                stage.status = "ok" if record.created else "duplicate"
                stage.detail = (
                    f"{record.stored.risk_level} score={record.stored.risk_score:.4f} "
                    f"methods={','.join(record.stored.detection_methods) or 'none'}"
                )
        except RiskServiceError as exc:
            return self._finish(
                log, payload, started, risk_summary, None, None, None, f"detection failed: {exc}"
            )
        except Exception as exc:  # noqa: BLE001
            return self._finish(
                log,
                payload,
                started,
                risk_summary,
                None,
                None,
                None,
                f"detection failed: {type(exc).__name__}: {exc}",
            )

        stored = self._risk.result(payload.message_id)
        event = (
            RiskAssessedPayload.from_stored(stored, synthetic=payload.synthetic)
            .with_dataset(payload.dataset_id)
            .to_event(trace_id=payload.trace_id)
        )

        if publish and self._publisher is not None:
            # A failed publication must not lose the committed risk result, but it
            # must be visible: the stage is marked failed and the outcome becomes
            # partial instead of reporting a clean success.
            with log.run("publish") as stage:
                try:
                    self._publisher.publish(self._risk_topic, event)
                    stage.detail = f"topic={self._risk_topic}"
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning(
                        "claro_processing_publish_failed",
                        message_id=str(payload.message_id),
                        error=str(exc),
                    )
                    stage.status = "failed"
                    stage.detail = f"publish failed: {type(exc).__name__}: {exc}"
                    error = stage.detail
        elif publish:
            log.entries.append(
                StageResult(
                    "publish",
                    "skipped",
                    0.0,
                    "no event publisher configured; governance ran in-process",
                )
            )

        decision: dict[str, Any] | None = None
        case_id: str | None = None
        enforcement_id: str | None = None
        try:
            with log.run("governance") as stage:
                handling = self._governance.handle(
                    ConsumedMessage(
                        event=event,
                        topic=self._risk_topic,
                        partition=0,
                        offset=0,
                        received_at=datetime.now(UTC),
                        headers={},
                    )
                )
                stage.status = "ok" if handling.status == "processed" else "duplicate"
                decision = self._repository.decision_for_message(payload.message_id)
                if decision is not None:
                    case = self._repository.case_for_message(payload.message_id)
                    case_id = str(case["id"]) if case else None
                    enforcement = self._repository.enforcement_for_decision(
                        UUID(str(decision["id"]))
                    )
                    enforcement_id = str(enforcement["id"]) if enforcement else None
                    stage.detail = (
                        f"action={decision['action']} status={decision['decision_status']}"
                    )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning(
                "claro_processing_governance_failed",
                message_id=str(payload.message_id),
                error=str(exc),
            )
            error = f"governance failed: {type(exc).__name__}: {exc}"

        return self._finish(
            log, payload, started, risk_summary, decision, case_id, enforcement_id, error
        )

    def process_batch(
        self,
        payloads: list[RawGameMessagePayload],
        *,
        publish: bool = True,
        retry_failures: bool = True,
    ) -> list[ProcessingOutcome]:
        """Process messages in order, retrying each failure once when enabled.

        A retry re-enters the same idempotent stages, so a transient Kafka or
        PostgreSQL error is recovered without duplicating business state.
        """
        outcomes: list[ProcessingOutcome] = []
        for payload in payloads:
            outcome = self.process_message(payload, publish=publish)
            if retry_failures and outcome.status in {"failed", "partial"}:
                self._logger.info(
                    "claro_processing_retry",
                    message_id=str(payload.message_id),
                    status=outcome.status,
                )
                retried = self.process_message(payload, publish=publish)
                combined = outcome.stages + tuple(
                    StageResult(f"retry.{item.name}", item.status, item.elapsed_ms, item.detail)
                    for item in retried.stages
                )
                outcome = ProcessingOutcome(
                    message_id=retried.message_id,
                    external_message_id=retried.external_message_id,
                    trace_id=retried.trace_id,
                    status=retried.status,
                    stages=combined,
                    risk=retried.risk or outcome.risk,
                    decision=retried.decision or outcome.decision,
                    case_id=retried.case_id or outcome.case_id,
                    enforcement_id=retried.enforcement_id or outcome.enforcement_id,
                    error=retried.error,
                    dataset_name=retried.dataset_name,
                    total_ms=outcome.total_ms + retried.total_ms,
                )
            outcomes.append(outcome)
        return outcomes

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _ingest(self, payload: RawGameMessagePayload, *, transport: str) -> IngestionResult:
        topic = (
            f"{DIRECT_TOPIC_PREFIX}.{payload.message_id}"
            if transport == DIRECT_TRANSPORT
            else self._processed_topic
        )
        # The dedupe hash must be content-addressed: it may not include the send
        # timestamp, otherwise replaying the same message looks like a different
        # payload and ingestion would reject the retry.
        stable_envelope = {
            "event_id": str(payload.message_id),
            "event_type": RAW_GAME_MESSAGE_EVENT,
            "payload": payload.model_dump(mode="json"),
        }
        return persist_raw_message(
            self._sessions,
            payload,
            source_topic=topic,
            source_partition=0,
            source_offset=0,
            payload_hash=event_payload_hash(stable_envelope),
            sent_at=payload.occurred_at,
            received_at=datetime.now(UTC),
            attempts=1,
            transport=transport,
        )

    def _finish(
        self,
        log: _StageLog,
        payload: RawGameMessagePayload,
        started: float,
        risk: dict[str, Any] | None,
        decision: dict[str, Any] | None,
        case_id: str | None,
        enforcement_id: str | None,
        error: str | None,
    ) -> ProcessingOutcome:
        stages = tuple(log.entries)
        return ProcessingOutcome(
            message_id=payload.message_id,
            external_message_id=payload.external_message_id,
            trace_id=payload.trace_id,
            status=_derive_status(stages),
            stages=stages,
            risk=risk,
            decision=decision,
            case_id=case_id,
            enforcement_id=enforcement_id,
            error=error,
            dataset_name=payload.dataset_name,
            total_ms=(time.perf_counter() - started) * 1000,
        )


def _derive_status(stages: tuple[StageResult, ...]) -> OutcomeStatus:
    """Map stage outcomes onto a single honest overall status.

    * any failed ingest → ``failed`` (nothing was persisted);
    * any other failed stage → ``partial`` (earlier state is committed);
    * a stage that created state → ``processed``;
    * everything reported duplicate → ``duplicate`` (idempotent replay).
    """
    failed = [item for item in stages if item.status == "failed"]
    if failed:
        if any(item.name == "ingest" for item in failed):
            return "failed"
        return "partial"
    if any(item.status == "ok" and item.name in {"detect", "governance"} for item in stages):
        return "processed"
    return "duplicate"


def _summarise_risk(risk: dict[str, Any] | None) -> dict[str, Any] | None:
    if not risk:
        return None
    return {
        "risk_result_id": risk.get("risk_result_id"),
        "risk_level": risk.get("risk_level"),
        "risk_score": round(float(risk.get("risk_score", 0.0)), 4),
        "confidence": round(float(risk.get("confidence", 0.0)), 4),
        "suggested_action": risk.get("suggested_action"),
        "detection_methods": list(risk.get("detection_methods") or []),
        "categories": [
            {"category": item.get("category"), "score": item.get("score")}
            for item in (risk.get("categories") or [])[:5]
        ],
    }


def _summarise_decision(decision: dict[str, Any] | None) -> dict[str, Any] | None:
    if not decision:
        return None
    return {
        "decision_id": decision.get("id"),
        "action": decision.get("action"),
        "status": decision.get("decision_status"),
        "requires_review": decision.get("requires_review"),
        "reason": decision.get("decision_reason"),
        "policy_id": decision.get("policy_id"),
        "decided_at": decision.get("decided_at"),
    }
