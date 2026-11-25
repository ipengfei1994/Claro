"""Shared filter object pushed down to every analytics query."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class AnalyticsFilters:
    """Filters applied to the scoped message set.

    ``start`` is inclusive, ``end`` is exclusive. Risk category and severity
    filters narrow the risk-event side only; message totals stay unchanged so
    that Risk Rate keeps one denominator across all pages.
    """

    start: datetime
    end: datetime
    dataset_id: UUID | None = None
    dataset_name: str | None = None
    server_ref: str | None = None
    alliance_ref: str | None = None
    player_ref: str | None = None
    risk_category: str | None = None
    risk_severity: str | None = None
    policy_key: str | None = None
    policy_version: int | None = None
    model_id: str | None = None
    repeat_threshold: int = 2

    def __post_init__(self) -> None:
        if isinstance(self.start, str):
            object.__setattr__(self, "start", datetime.fromisoformat(self.start))
        if isinstance(self.end, str):
            object.__setattr__(self, "end", datetime.fromisoformat(self.end))
        if self.start.tzinfo is None:
            object.__setattr__(self, "start", self.start.replace(tzinfo=UTC))
        if self.end.tzinfo is None:
            object.__setattr__(self, "end", self.end.replace(tzinfo=UTC))
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.repeat_threshold < 2:
            raise ValueError("repeat_threshold must be at least 2")

    @classmethod
    def default(cls, *, days: int = 365) -> AnalyticsFilters:
        end = datetime.now(UTC)
        return cls(start=end - timedelta(days=days), end=end)

    def with_dataset(self, dataset_id: UUID | None, dataset_name: str | None) -> AnalyticsFilters:
        return replace(self, dataset_id=dataset_id, dataset_name=dataset_name)

    def params(self) -> dict[str, Any]:
        """Parameters for the shared scoped-message SQL CTE."""
        return {
            "start": self.start,
            "end": self.end,
            "dataset_id": self.dataset_id,
            "dataset_name": self.dataset_name,
            "server_ref": self.server_ref,
            "alliance_ref": self.alliance_ref,
            "player_ref": self.player_ref,
            "risk_category": self.risk_category,
            "risk_severity": self.risk_severity,
            "repeat_threshold": self.repeat_threshold,
            "policy_key": self.policy_key,
            "policy_version": self.policy_version,
            "model_id": self.model_id,
        }

    def summary(self) -> dict[str, Any]:
        """Human-readable filter description used in reports and page headers."""
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "dataset": self.dataset_name
            or ("dataset_id=" + str(self.dataset_id) if self.dataset_id else "all"),
            "server": self.server_ref or "all",
            "alliance": self.alliance_ref or "all",
            "player": self.player_ref or "all",
            "risk_category": self.risk_category or "all",
            "risk_severity": self.risk_severity or "all",
            "policy": self.policy_key or "all",
            "policy_version": self.policy_version,
            "model": self.model_id or "all",
        }


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """Return UTC half-open day bounds for a calendar date."""
    start = datetime.combine(day, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)
