"""Read-only repository for analytical queries.

The repository owns SQL execution. Services own metric interpretation. No
method in this module writes to business tables.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.engine import RowMapping

from claro.analytics import sql_queries as q
from claro.analytics.filters import AnalyticsFilters


def rows_to_dicts(rows: Sequence[RowMapping]) -> list[dict[str, Any]]:
    """Convert SQLAlchemy mappings into plain dictionaries."""
    return [dict(row) for row in rows]


class AnalyticsRepository:
    """Execute the centralised analytics SQL against PostgreSQL."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def _all(self, sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        with self._engine.connect() as connection:
            return rows_to_dicts(connection.execute(text(sql), dict(params)).mappings().all())

    def _one(self, sql: str, params: Mapping[str, Any]) -> dict[str, Any]:
        with self._engine.connect() as connection:
            row = connection.execute(text(sql), dict(params)).mappings().one()
            return dict(row)

    def datasets(self) -> list[dict[str, Any]]:
        return self._all(q.SQL_DATASET_INFO, {})

    def overview(self, filters: AnalyticsFilters) -> dict[str, Any]:
        params = filters.params()
        result = self._one(q.SQL_OVERVIEW, params)
        result["repeat_offenders"] = self._one(q.SQL_REPEAT_OFFENDERS, params)["repeat_offenders"]
        return result

    def time_series(self, filters: AnalyticsFilters, grain: q.Grain) -> list[dict[str, Any]]:
        return self._all(q.daily_counts_sql(grain), filters.params())

    def category_distribution(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return self._all(q.SQL_CATEGORY_DISTRIBUTION, filters.params())

    def severity_distribution(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return self._all(q.SQL_SEVERITY_DISTRIBUTION, filters.params())

    def cooccurrence(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return self._all(q.SQL_COOCCURRENCE, filters.params())

    def server_ranking(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return self._all(q.SQL_SERVER_RANKING, filters.params())

    def alliance_ranking(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return self._all(q.SQL_ALLIANCE_RANKING, filters.params())

    def player_profiles(self, filters: AnalyticsFilters, limit: int = 100) -> list[dict[str, Any]]:
        params = {**filters.params(), "limit": limit}
        return self._all(q.SQL_PLAYER_PROFILE, params)

    def governance_totals(self, filters: AnalyticsFilters) -> dict[str, Any]:
        return self._one(q.SQL_GOVERNANCE_TOTALS, filters.params())

    def decision_distribution(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return self._all(q.SQL_DECISION_DISTRIBUTION, filters.params())

    def moderation_totals(self, filters: AnalyticsFilters) -> dict[str, Any]:
        return self._one(q.SQL_MODERATION_TOTALS, filters.params())

    def moderation_by_status(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return self._all(q.SQL_MODERATION_BY_STATUS, filters.params())

    def enforcement_distribution(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return self._all(q.SQL_ENFORCEMENT_DISTRIBUTION, filters.params())

    def model_runs(self, model_id: str | None = None) -> list[dict[str, Any]]:
        return self._all(q.SQL_MODEL_RUNS, {"model_id": model_id})

    def model_error_cases(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return self._all(q.SQL_MODEL_ERROR_CASES, filters.params())

    def observed_risk_vs_label(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return self._all(q.SQL_OBSERVED_RISK_VS_LABEL, filters.params())

    def policy_hits(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return self._all(q.SQL_POLICY_HITS, filters.params())

    def policy_quality(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        """Per-policy identification quality against the synthetic ground truth."""
        return self._all(q.SQL_POLICY_QUALITY, filters.params())

    def detection_quality(self, filters: AnalyticsFilters) -> dict[str, Any]:
        """Detection-layer confusion matrix against the synthetic ground truth."""
        return self._one(q.SQL_DETECTION_QUALITY, filters.params())

    def policy_evaluation_actions(self, filters: AnalyticsFilters) -> list[dict[str, Any]]:
        return self._all(q.SQL_POLICY_EVALUATION_ACTIONS, filters.params())

    def replay_input(self, filters: AnalyticsFilters, limit: int) -> list[dict[str, Any]]:
        params = {**filters.params(), "limit": limit}
        return self._all(q.SQL_REPLAY_INPUT, params)

    def replay_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        return self._all(q.SQL_REPLAY_RUNS, {"limit": limit})

    def replay_summary(self, run_id: UUID | None = None, limit: int = 25) -> list[dict[str, Any]]:
        return self._all(q.SQL_REPLAY_SUMMARY, {"run_id": run_id, "limit": limit})

    def replay_cases(self, run_id: UUID) -> list[dict[str, Any]]:
        return self._all(q.SQL_REPLAY_DIFF, {"run_id": run_id})

    def quality_orphans(self) -> dict[str, Any]:
        return self._one(q.SQL_DQ_ORPHANS, {})

    def quality_duplicates(self) -> dict[str, Any]:
        return self._one(q.SQL_DQ_DUPLICATES, {})

    def quality_coverage(self) -> dict[str, Any]:
        return self._one(q.SQL_DQ_COVERAGE, {})

    def quality_time(self) -> dict[str, Any]:
        return self._one(q.SQL_DQ_TIME, {})
