"""Read models for message exploration, risk intelligence and the overview.

The service translates repository rows into values the UI can render directly:
parsed timestamps, normalised enums, human-readable labels and explicit
missing-data markers. It performs no writes and owns no SQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from claro.analytics.filters import AnalyticsFilters
from claro.analytics.services import AnalyticsService
from claro.data_access.repositories.explorer_repository import ExplorerRepository
from claro.data_access.repositories.governance_repository import GovernanceRepository

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200
VALID_RISK_LEVELS = frozenset({"normal", "low", "medium", "high", "critical"})


class ExplorerError(ValueError):
    """Raised when a filter or identifier is not usable."""


@dataclass(frozen=True, slots=True)
class SearchPage:
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return max(1, -(-self.total // self.page_size))

    @property
    def first_row(self) -> int:
        return 0 if not self.items else (self.page - 1) * self.page_size + 1

    @property
    def last_row(self) -> int:
        return (self.page - 1) * self.page_size + len(self.items)


class ExplorerService:
    """Facade used by the Overview, Message Explorer and Risk Intelligence pages."""

    def __init__(
        self,
        repository: ExplorerRepository,
        governance_repository: GovernanceRepository,
        analytics_service: AnalyticsService,
    ) -> None:
        self._repository = repository
        self._governance = governance_repository
        self._analytics = analytics_service

    # ------------------------------------------------------------------
    # Message explorer
    # ------------------------------------------------------------------
    def options(self) -> dict[str, list[str]]:
        return self._repository.filter_options()

    def search(
        self,
        *,
        dataset: str | None = None,
        channel: str | None = None,
        risk_level: str | None = None,
        category: str | None = None,
        decision_action: str | None = None,
        case_status: str | None = None,
        text: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> SearchPage:
        if page < 1:
            raise ExplorerError("page must be >= 1")
        size = max(1, min(int(page_size), MAX_PAGE_SIZE))
        if risk_level and risk_level not in VALID_RISK_LEVELS:
            raise ExplorerError(f"unknown risk level: {risk_level}")
        if start and end and start >= end:
            raise ExplorerError("start must be before end")
        needle = (text or "").strip()[:120] or None
        filters = {
            "dataset": dataset or None,
            "channel": channel or None,
            "risk_level": risk_level or None,
            "category": category or None,
            "decision_action": decision_action or None,
            "case_status": case_status or None,
            "search": needle,
            "start_at": start,
            "end_at": end,
            "limit": size,
            "offset": (page - 1) * size,
        }
        result = self._repository.search_messages(filters)
        return SearchPage(
            items=[_message_row(item) for item in result["items"]],
            total=result["total"],
            page=page,
            page_size=size,
        )

    def detail(self, message_id: str | UUID) -> dict[str, Any]:
        try:
            identifier = UUID(str(message_id))
        except (TypeError, ValueError) as error:
            raise ExplorerError("message id must be a UUID") from error
        bundle = self._repository.message_bundle(identifier)
        if not bundle["header"]:
            raise ExplorerError(f"message not found: {identifier}")
        governance = self._safe_trace(identifier)
        return {
            "header": _message_row(bundle["header"]),
            "risk_result": _risk_result(bundle["risk_result"]),
            "risk_events": [_risk_event(item) for item in bundle["risk_events"]],
            "findings": [_finding(item) for item in bundle["findings"]],
            "trace": [_trace_step(item) for item in bundle["trace"]],
            "audit": bundle["audit"],
            "case_events": bundle["case_events"],
            "reviews": bundle["reviews"],
            "feedback": bundle["feedback"],
            "governance": governance,
        }

    def _safe_trace(self, message_id: UUID) -> dict[str, Any] | None:
        try:
            return self._governance.governance_trace(message_id)
        except Exception:  # noqa: BLE001 - trace is supporting evidence, never fatal
            return None

    # ------------------------------------------------------------------
    # Risk intelligence
    # ------------------------------------------------------------------
    def risk_intelligence(self) -> dict[str, Any]:
        return {
            "rules": self._repository.rule_catalog(),
            "detectors": self._repository.detector_summary(),
            "taxonomy": self._repository.taxonomy_usage(),
            "models": [_model_card(item) for item in self._repository.model_cards()],
            "evaluations": self._repository.evaluation_runs(),
            "coverage": self._repository.detection_coverage(),
        }

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------
    def overview(self, *, days: int = 30) -> dict[str, Any]:
        window = max(1, min(int(days), 365))
        end = datetime.now(UTC)
        start = end - timedelta(days=window)
        analytics_filters = AnalyticsFilters(start=start, end=end)
        kpis = self._analytics.overview(analytics_filters)
        return {
            "window_days": window,
            "start": start,
            "end": end,
            "kpis": kpis["kpis"],
            "coverage": kpis["coverage"],
            "quality": kpis["quality"],
            "notes": kpis.get("notes", []),
            "timeline": self._repository.daily_timeline(start),
            "categories": self._repository.category_breakdown(start),
            "severities": self._repository.severity_breakdown(start),
            "servers": self._repository.server_risk(start),
            "decisions": self._repository.decision_mix(start),
            "workload": self._repository.workload_totals(),
            "activity": [_activity(item) for item in self._repository.activity(12)],
            "datasets": self._repository.dataset_summary(),
        }


# ---------------------------------------------------------------------------
# Row normalisation
# ---------------------------------------------------------------------------
def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
        return moment.isoformat()
    return str(value)


def _message_row(row: dict[str, Any]) -> dict[str, Any]:
    content = str(row.get("content") or "")
    return {
        "message_id": str(row.get("message_id")),
        "external_message_id": row.get("external_message_id"),
        "sender_ref": row.get("sender_ref"),
        "server_ref": row.get("server_ref"),
        "channel": row.get("channel"),
        "content": content,
        "excerpt": content if len(content) <= 96 else f"{content[:96]}…",
        "status": row.get("status"),
        "display_status": row.get("display_status"),
        "occurred_at": _iso(row.get("occurred_at")),
        "ingested_at": _iso(row.get("ingested_at")),
        "is_synthetic": bool(row.get("is_synthetic")),
        "dataset_name": row.get("dataset_name"),
        "risk_level": row.get("risk_level") or row.get("event_severity"),
        "risk_score": _float(row.get("risk_score")),
        "confidence": _float(row.get("confidence")),
        "suggested_action": row.get("suggested_action"),
        "top_category": row.get("event_category"),
        "event_count": int(row.get("event_count") or 0),
        "decision_action": row.get("decision_action"),
        "decision_status": row.get("decision_status"),
        "requires_review": row.get("requires_review"),
        "case_status": row.get("case_status"),
        "case_priority": row.get("case_priority"),
        "detection_methods": list(row.get("detection_methods") or []),
    }


def _risk_result(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "risk_result_id": str(row.get("risk_result_id")),
        "risk_score": _float(row.get("risk_score")),
        "risk_level": row.get("risk_level"),
        "suggested_action": row.get("suggested_action"),
        "confidence": _float(row.get("confidence")),
        "categories": list(row.get("categories") or []),
        "detection_methods": list(row.get("detection_methods") or []),
        "evidence": row.get("evidence") or {},
        "explanation": row.get("explanation") or {},
        "detector_versions": row.get("detector_versions") or {},
        "timings": row.get("timings") or {},
        "detected_at": _iso(row.get("detected_at")),
    }


def _risk_event(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": str(row.get("event_id")),
        "rule_id": str(row.get("rule_id")) if row.get("rule_id") else None,
        "category": row.get("category"),
        "event_type": row.get("event_type"),
        "risk_score": _float(row.get("risk_score")),
        "confidence": _float(row.get("confidence")),
        "severity": row.get("severity"),
        "occurred_at": _iso(row.get("occurred_at")),
        "details": row.get("details") or {},
    }


def _finding(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "finding_id": str(row.get("finding_id")),
        "rule_id": str(row.get("rule_id")) if row.get("rule_id") else None,
        "detector": row.get("detector"),
        "detector_version": row.get("detector_version"),
        "category": row.get("category"),
        "score": _float(row.get("score")),
        "confidence": _float(row.get("confidence")),
        "evidence": row.get("evidence") or {},
        "created_at": _iso(row.get("created_at")),
    }


def _trace_step(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "sequence": int(row.get("sequence") or 0),
        "stage": row.get("stage"),
        "status": row.get("status"),
        "started_at": _iso(row.get("started_at")),
        "finished_at": _iso(row.get("finished_at")),
        "details": row.get("details") or {},
    }


def _activity(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": row.get("kind"),
        "entity_id": row.get("entity_id"),
        "occurred_at": _iso(row.get("occurred_at")),
        "actor_ref": row.get("actor_ref"),
        "summary": row.get("summary"),
        "message_id": row.get("message_id"),
    }


def _model_card(row: dict[str, Any]) -> dict[str, Any]:
    metrics = row.get("metrics") or {}
    return {
        "model_id": row.get("id"),
        "name": row.get("name"),
        "version": row.get("version"),
        "algorithm": row.get("algorithm"),
        "dataset_name": row.get("dataset_name"),
        "status": row.get("status"),
        "trained_at": _iso(row.get("trained_at")),
        "last_evaluated": _iso(row.get("last_evaluated")),
        "artifact_path": row.get("artifact_path"),
        "metrics": metrics,
        "features": row.get("feature_config") or {},
    }


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
