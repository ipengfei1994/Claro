"""Read-only queries for the message explorer and risk intelligence pages.

The repository owns SQL; the service layer interprets results; the UI renders
them. Every statement is parameterised — no user input is ever interpolated into
SQL. Filters with an empty value are neutralised by NULL checks in SQL, which
keeps one prepared statement per query shape.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.engine import RowMapping

_SEVERITY_RANK = """
    CASE re.severity
        WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2
        WHEN 'low' THEN 1 ELSE 0 END
"""

# ---------------------------------------------------------------------------
# Message search
# ---------------------------------------------------------------------------
# One row per message, enriched with detection, decision and case state. The
# lateral joins keep the query O(matching messages) rather than fanning out on
# multi-row children (one message can have several risk events).
SQL_SEARCH_MESSAGES = f"""
SELECT
    m.id                        AS message_id,
    m.external_message_id,
    m.sender_ref,
    m.server_ref,
    m.channel,
    m.content,
    m.status,
    m.display_status,
    m.occurred_at,
    m.is_synthetic,
    d.name                      AS dataset_name,
    rr.risk_level               AS risk_level,
    rr.risk_score               AS risk_score,
    rr.confidence               AS confidence,
    rr.suggested_action         AS suggested_action,
    rr.detection_methods        AS detection_methods,
    ev.event_count              AS event_count,
    ev.top_severity             AS event_severity,
    ev.top_category             AS event_category,
    dec.action                  AS decision_action,
    dec.decision_status         AS decision_status,
    dec.requires_review         AS requires_review,
    mc.status                   AS case_status,
    mc.priority                 AS case_priority
FROM message m
LEFT JOIN dataset d ON d.id = m.dataset_id
LEFT JOIN risk_result rr ON rr.message_id = m.id
LEFT JOIN LATERAL (
    SELECT count(*) AS event_count,
           (array_agg(re.severity ORDER BY {_SEVERITY_RANK} DESC))[1] AS top_severity,
           (array_agg(re.category ORDER BY {_SEVERITY_RANK} DESC))[1] AS top_category
    FROM risk_event re
    WHERE re.message_id = m.id
) ev ON TRUE
LEFT JOIN LATERAL (
    SELECT pd.action, pd.decision_status, pd.requires_review
    FROM policy_decision pd
    WHERE pd.message_id = m.id
    ORDER BY pd.decided_at DESC
    LIMIT 1
) dec ON TRUE
LEFT JOIN LATERAL (
    SELECT c.status, c.priority
    FROM moderation_case c
    WHERE c.message_id = m.id
    LIMIT 1
) mc ON TRUE
WHERE (CAST(:dataset AS text) IS NULL OR d.name = CAST(:dataset AS text))
  AND (CAST(:channel AS text) IS NULL OR m.channel = CAST(:channel AS text))
  AND (CAST(:search AS text) IS NULL
       OR m.content ILIKE '%' || CAST(:search AS text) || '%'
       OR m.sender_ref ILIKE '%' || CAST(:search AS text) || '%'
       OR m.external_message_id ILIKE '%' || CAST(:search AS text) || '%')
  AND (CAST(:start_at AS timestamptz) IS NULL OR m.occurred_at >= CAST(:start_at AS timestamptz))
  AND (CAST(:end_at AS timestamptz) IS NULL OR m.occurred_at < CAST(:end_at AS timestamptz))
  AND (CAST(:risk_level AS text) IS NULL
       OR COALESCE(rr.risk_level, ev.top_severity) = CAST(:risk_level AS text))
  AND (CAST(:category AS text) IS NULL OR ev.top_category = CAST(:category AS text))
  AND (CAST(:decision_action AS text) IS NULL OR dec.action = CAST(:decision_action AS text))
  AND (CAST(:case_status AS text) IS NULL OR mc.status = CAST(:case_status AS text))
ORDER BY m.occurred_at DESC, m.id DESC
LIMIT :limit OFFSET :offset
"""

SQL_COUNT_MESSAGES = """
SELECT count(*) AS total
FROM message m
LEFT JOIN dataset d ON d.id = m.dataset_id
LEFT JOIN risk_result rr ON rr.message_id = m.id
LEFT JOIN LATERAL (
    SELECT (array_agg(re.severity ORDER BY CASE re.severity
        WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2
        WHEN 'low' THEN 1 ELSE 0 END DESC))[1] AS top_severity,
        (array_agg(re.category ORDER BY CASE re.severity
        WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2
        WHEN 'low' THEN 1 ELSE 0 END DESC))[1] AS top_category
    FROM risk_event re WHERE re.message_id = m.id
) ev ON TRUE
LEFT JOIN LATERAL (
    SELECT pd.action FROM policy_decision pd
    WHERE pd.message_id = m.id ORDER BY pd.decided_at DESC LIMIT 1
) dec ON TRUE
LEFT JOIN LATERAL (
    SELECT c.status FROM moderation_case c WHERE c.message_id = m.id LIMIT 1
) mc ON TRUE
WHERE (CAST(:dataset AS text) IS NULL OR d.name = CAST(:dataset AS text))
  AND (CAST(:channel AS text) IS NULL OR m.channel = CAST(:channel AS text))
  AND (CAST(:search AS text) IS NULL
       OR m.content ILIKE '%' || CAST(:search AS text) || '%'
       OR m.sender_ref ILIKE '%' || CAST(:search AS text) || '%'
       OR m.external_message_id ILIKE '%' || CAST(:search AS text) || '%')
  AND (CAST(:start_at AS timestamptz) IS NULL OR m.occurred_at >= CAST(:start_at AS timestamptz))
  AND (CAST(:end_at AS timestamptz) IS NULL OR m.occurred_at < CAST(:end_at AS timestamptz))
  AND (CAST(:risk_level AS text) IS NULL
       OR COALESCE(rr.risk_level, ev.top_severity) = CAST(:risk_level AS text))
  AND (CAST(:category AS text) IS NULL OR ev.top_category = CAST(:category AS text))
  AND (CAST(:decision_action AS text) IS NULL OR dec.action = CAST(:decision_action AS text))
  AND (CAST(:case_status AS text) IS NULL OR mc.status = CAST(:case_status AS text))
"""

SQL_MESSAGE_HEADER = """
SELECT m.id AS message_id, m.external_message_id, m.sender_ref, m.server_ref,
       m.channel, m.content, m.content_hash, m.language, m.status, m.display_status,
       m.occurred_at, m.ingested_at, m.is_synthetic, d.name AS dataset_name,
       p.player_ref AS player_ref, p.display_name AS player_display_name,
       s.name AS server_name, a.name AS alliance_name
FROM message m
LEFT JOIN dataset d ON d.id = m.dataset_id
LEFT JOIN player p ON p.id = m.player_id
LEFT JOIN server s ON s.id = m.server_id
LEFT JOIN alliance a ON a.id = m.alliance_id
WHERE m.id = :message_id
"""

SQL_MESSAGE_RISK_RESULT = """
SELECT id AS risk_result_id, risk_score, risk_level, suggested_action, confidence,
       categories, detection_methods, evidence, explanation, detector_versions,
       timings, detected_at, is_synthetic
FROM risk_result WHERE message_id = :message_id
"""

SQL_MESSAGE_RISK_EVENTS = f"""
SELECT id AS event_id, rule_id, category, event_type, risk_score, confidence,
       severity, occurred_at, details
FROM risk_event WHERE message_id = :message_id
ORDER BY {_SEVERITY_RANK} DESC, occurred_at DESC
"""

SQL_MESSAGE_FINDINGS = """
SELECT id AS finding_id, rule_id, detector, detector_version, category, score,
       confidence, evidence, created_at
FROM risk_finding WHERE message_id = :message_id
ORDER BY score DESC, created_at DESC
"""

SQL_MESSAGE_TRACE = """
SELECT sequence, stage, status, started_at, finished_at, details
FROM processing_event WHERE message_id = :message_id
ORDER BY sequence
"""

SQL_MESSAGE_AUDIT = """
SELECT entity_type, entity_id, action, actor_type, actor_ref, actor_role, reason,
       before_state, after_state, created_at
FROM audit_event
WHERE entity_id IN (
    SELECT CAST(:message_id AS uuid)
    UNION SELECT CAST(id AS uuid) FROM policy_decision WHERE message_id = CAST(:message_id AS uuid)
    UNION SELECT CAST(id AS uuid) FROM moderation_case WHERE message_id = CAST(:message_id AS uuid)
)
ORDER BY created_at
"""

SQL_MESSAGE_CASE_EVENTS = """
SELECT ce.case_id, ce.event_type, ce.actor_type, ce.actor_ref, ce.from_status,
       ce.to_status, ce.note, ce.created_at
FROM case_event ce
JOIN moderation_case mc ON mc.id = ce.case_id
WHERE mc.message_id = :message_id
ORDER BY ce.created_at
"""

SQL_MESSAGE_REVIEWS = """
SELECT mr.id AS review_id, mr.action, mr.reviewer_ref AS actor_ref,
       mr.reviewer_role AS actor_role, mr.reason, mr.notes, mr.created_at
FROM moderation_review mr
JOIN moderation_case mc ON mc.id = mr.case_id
WHERE mc.message_id = :message_id
ORDER BY mr.created_at
"""

SQL_MESSAGE_FEEDBACK = """
SELECT gf.id AS feedback_id, gf.feedback_type, gf.reviewer_ref AS actor_ref,
       gf.difference_reason AS notes, gf.created_at
FROM governance_feedback gf
WHERE gf.message_id = :message_id
ORDER BY gf.created_at
"""

# ---------------------------------------------------------------------------
# Filter options and reference data
# ---------------------------------------------------------------------------
SQL_FILTER_OPTIONS = """
SELECT
    (SELECT array_agg(name ORDER BY name) FROM dataset) AS datasets,
    (SELECT array_agg(DISTINCT channel ORDER BY channel) FROM message) AS channels,
    (SELECT array_agg(DISTINCT category ORDER BY category) FROM risk_event) AS categories
"""

SQL_RULE_CATALOG = """
SELECT dr.rule_key, dr.rule_type, dr.status, dr.version,
       COALESCE(dr.definition->>'category', '—') AS category,
       COALESCE(dr.definition->>'description', '') AS description,
       COALESCE(f.hits, 0) AS hits,
       f.last_seen
FROM detection_rule dr
LEFT JOIN (
    SELECT rule_id, count(*) AS hits, max(created_at) AS last_seen
    FROM risk_finding GROUP BY rule_id
) f ON f.rule_id = dr.id
ORDER BY COALESCE(f.hits, 0) DESC, dr.rule_key
"""

SQL_DETECTOR_SUMMARY = """
SELECT detector, count(*) AS findings, count(DISTINCT message_id) AS messages,
       max(created_at) AS last_seen
FROM risk_finding GROUP BY detector ORDER BY findings DESC
"""

SQL_TOXONOMY_USAGE = """
SELECT category,
       count(*) AS events,
       count(DISTINCT message_id) AS messages,
       round(avg(risk_score)::numeric, 4) AS avg_score
FROM risk_event GROUP BY category ORDER BY events DESC
"""

SQL_MODEL_CARDS = """
SELECT m.id, m.name, m.version, m.algorithm, m.dataset_name, m.status, m.trained_at,
       m.metrics, m.feature_config, m.artifact_path,
       (SELECT max(created_at) FROM evaluation_run e WHERE e.model_id = m.id) AS last_evaluated
FROM ml_model m
ORDER BY m.trained_at DESC
LIMIT 10
"""

SQL_EVALUATION_RUNS = """
SELECT id, model_id, dataset_name, split, message_count, metrics, created_at
FROM evaluation_run ORDER BY created_at DESC LIMIT 5
"""

SQL_DETECTION_COVERAGE = """
SELECT
    (SELECT count(*) FROM message) AS messages,
    (SELECT count(*) FROM risk_result) AS detected_messages,
    (SELECT count(*) FROM risk_finding) AS findings,
    (SELECT count(DISTINCT message_id) FROM risk_finding) AS findings_messages,
    (SELECT count(*) FROM risk_event) AS events,
    (SELECT count(DISTINCT message_id) FROM risk_event) AS events_messages
"""

# ---------------------------------------------------------------------------
# Overview aggregates
# ---------------------------------------------------------------------------
SQL_DAILY_TIMELINE = """
WITH severity_rank AS (
    SELECT message_id,
           max(CASE severity
                 WHEN 'critical' THEN 4 WHEN 'high' THEN 3
                 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END) AS rank
    FROM risk_event
    GROUP BY message_id
), scored AS (
    SELECT m.occurred_at,
           COALESCE(rr.risk_level,
                    CASE sr.rank WHEN 4 THEN 'critical' WHEN 3 THEN 'high'
                                 WHEN 2 THEN 'medium' WHEN 1 THEN 'low' END) AS level
    FROM message m
    LEFT JOIN risk_result rr ON rr.message_id = m.id
    LEFT JOIN severity_rank sr ON sr.message_id = m.id
    WHERE m.occurred_at >= :start_at
)
SELECT date_trunc('day', occurred_at)::date AS day,
       count(*) AS messages,
       count(*) FILTER (WHERE level IS NOT NULL AND level <> 'normal') AS risk_messages,
       count(*) FILTER (WHERE level IN ('high', 'critical')) AS high_risk_messages
FROM scored
GROUP BY 1 ORDER BY 1
"""

SQL_CATEGORY_BREAKDOWN = """
SELECT category, count(*) AS events, count(DISTINCT message_id) AS messages
FROM risk_event
WHERE occurred_at >= :start_at
GROUP BY category ORDER BY events DESC
"""

SQL_SEVERITY_BREAKDOWN = """
SELECT severity, count(*) AS events
FROM risk_event
WHERE occurred_at >= :start_at
GROUP BY severity
"""

SQL_SERVER_RISK = """
WITH severity_rank AS (
    SELECT message_id,
           max(CASE severity
                 WHEN 'critical' THEN 4 WHEN 'high' THEN 3
                 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END) AS rank
    FROM risk_event
    GROUP BY message_id
), scored AS (
    SELECT COALESCE(m.server_ref, '未标记') AS server_ref,
           COALESCE(rr.risk_level,
                    CASE sr.rank WHEN 4 THEN 'critical' WHEN 3 THEN 'high'
                                 WHEN 2 THEN 'medium' WHEN 1 THEN 'low' END) AS level
    FROM message m
    LEFT JOIN risk_result rr ON rr.message_id = m.id
    LEFT JOIN severity_rank sr ON sr.message_id = m.id
    WHERE m.occurred_at >= :start_at
)
SELECT server_ref,
       count(*) AS messages,
       count(*) FILTER (WHERE level IN ('high', 'critical')) AS high_risk_messages,
       count(*) FILTER (WHERE level IS NOT NULL AND level <> 'normal') AS risk_messages
FROM scored
GROUP BY 1 ORDER BY high_risk_messages DESC, risk_messages DESC
LIMIT 10
"""

SQL_DECISION_MIX = """
SELECT action, count(*) AS decisions
FROM policy_decision WHERE decided_at >= :start_at
GROUP BY action ORDER BY decisions DESC
"""

SQL_WORKLOAD_TOTALS = """
SELECT
    (SELECT count(*) FROM moderation_case
       WHERE status IN ('open', 'pending', 'in_review', 'escalated', 'second_review'))
        AS pending_cases,
    (SELECT count(*) FROM moderation_case WHERE status IN ('open', 'pending', 'in_review',
        'escalated', 'second_review') AND due_at IS NOT NULL AND due_at < now())
        AS overdue_cases,
    (SELECT count(*) FROM enforcement_action WHERE status = 'executed') AS active_enforcements,
    (SELECT count(*) FROM governance_feedback) AS feedback_rows,
    (SELECT count(*) FROM moderation_review) AS reviews,
    (SELECT count(*) FROM outbox_event WHERE status <> 'published') AS pending_outbox
"""

SQL_ACTIVITY_FEED = """
SELECT * FROM (
    SELECT 'decision' AS kind, pd.id::text AS entity_id, pd.decided_at AS occurred_at,
           pd.decided_by AS actor_ref,
           concat('治理决策 · ', pd.action, ' · ', coalesce(pd.decision_reason, '')) AS summary,
           pd.message_id::text AS message_id
    FROM policy_decision pd
    WHERE pd.decision_status IS NOT NULL
    UNION ALL
    SELECT 'review' AS kind, mr.id::text, mr.created_at, mr.reviewer_ref,
           concat('人工审核 · ', mr.action, ' · ', coalesce(mr.reason, '')), mc.message_id::text
    FROM moderation_review mr JOIN moderation_case mc ON mc.id = mr.case_id
    UNION ALL
    SELECT 'enforcement' AS kind, ea.id::text, ea.created_at, null,
           concat('模拟处置 · ', ea.action_type, ' · ', ea.status), null
    FROM enforcement_action ea
    UNION ALL
    SELECT 'policy' AS kind, pv.id::text, pv.created_at, pv.created_by,
           concat('策略版本 · ', pv.name, ' v', pv.version), null
    FROM policy_version pv
    UNION ALL
    SELECT 'feedback' AS kind, gf.id::text, gf.created_at, gf.reviewer_ref,
           concat('反馈 · ', gf.feedback_type), gf.message_id::text
    FROM governance_feedback gf
    UNION ALL
    SELECT 'case' AS kind, ce.id::text, ce.created_at, ce.actor_ref,
           concat('案例流转 · ', ce.event_type, ' → ', coalesce(ce.to_status, '')), null
    FROM case_event ce
) feed
ORDER BY occurred_at DESC
LIMIT :limit
"""

SQL_DATASET_SUMMARY = """
SELECT d.name, d.is_synthetic, d.created_at,
       COALESCE(msg.messages, 0) AS messages,
       COALESCE(det.detected, 0) AS detected,
       COALESCE(cs.cases, 0) AS cases
FROM dataset d
LEFT JOIN (
    SELECT dataset_id, count(*) AS messages FROM message GROUP BY dataset_id
) msg ON msg.dataset_id = d.id
LEFT JOIN (
    SELECT dataset_id, count(*) AS detected FROM risk_result GROUP BY dataset_id
) det ON det.dataset_id = d.id
LEFT JOIN (
    SELECT m.dataset_id, count(*) AS cases
    FROM moderation_case mc JOIN message m ON m.id = mc.message_id
    GROUP BY m.dataset_id
) cs ON cs.dataset_id = d.id
ORDER BY d.created_at DESC
"""


def _rows(rows: Sequence[RowMapping]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


class ExplorerRepository:
    """Read-only access for exploration, risk intelligence and overview pages."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # -- helpers -------------------------------------------------------
    def _all(self, sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        with self._engine.connect() as connection:
            return _rows(connection.execute(text(sql), dict(params)).mappings().all())

    def _one(self, sql: str, params: Mapping[str, Any]) -> dict[str, Any] | None:
        with self._engine.connect() as connection:
            row = connection.execute(text(sql), dict(params)).mappings().first()
            return dict(row) if row is not None else None

    # -- message explorer ---------------------------------------------
    def search_messages(self, filters: Mapping[str, Any]) -> dict[str, Any]:
        params = dict(filters)
        items = self._all(SQL_SEARCH_MESSAGES, params)
        total = self._one(SQL_COUNT_MESSAGES, params)
        return {"items": items, "total": int(total["total"]) if total else 0}

    def message_header(self, message_id: UUID) -> dict[str, Any] | None:
        return self._one(SQL_MESSAGE_HEADER, {"message_id": message_id})

    def message_bundle(self, message_id: UUID) -> dict[str, Any]:
        params = {"message_id": message_id}
        return {
            "header": self._one(SQL_MESSAGE_HEADER, params),
            "risk_result": self._one(SQL_MESSAGE_RISK_RESULT, params),
            "risk_events": self._all(SQL_MESSAGE_RISK_EVENTS, params),
            "findings": self._all(SQL_MESSAGE_FINDINGS, params),
            "trace": self._all(SQL_MESSAGE_TRACE, params),
            "audit": self._all(SQL_MESSAGE_AUDIT, params),
            "case_events": self._all(SQL_MESSAGE_CASE_EVENTS, params),
            "reviews": self._all(SQL_MESSAGE_REVIEWS, params),
            "feedback": self._all(SQL_MESSAGE_FEEDBACK, params),
        }

    def filter_options(self) -> dict[str, list[str]]:
        row = self._one(SQL_FILTER_OPTIONS, {}) or {}
        return {
            "datasets": list(row.get("datasets") or []),
            "channels": list(row.get("channels") or []),
            "categories": list(row.get("categories") or []),
        }

    # -- risk intelligence --------------------------------------------
    def rule_catalog(self) -> list[dict[str, Any]]:
        return self._all(SQL_RULE_CATALOG, {})

    def detector_summary(self) -> list[dict[str, Any]]:
        return self._all(SQL_DETECTOR_SUMMARY, {})

    def taxonomy_usage(self) -> list[dict[str, Any]]:
        return self._all(SQL_TOXONOMY_USAGE, {})

    def model_cards(self) -> list[dict[str, Any]]:
        return self._all(SQL_MODEL_CARDS, {})

    def evaluation_runs(self) -> list[dict[str, Any]]:
        return self._all(SQL_EVALUATION_RUNS, {})

    def detection_coverage(self) -> dict[str, Any]:
        return self._one(SQL_DETECTION_COVERAGE, {}) or {}

    # -- overview -------------------------------------------------------
    def daily_timeline(self, start_at: Any) -> list[dict[str, Any]]:
        return self._all(SQL_DAILY_TIMELINE, {"start_at": start_at})

    def category_breakdown(self, start_at: Any) -> list[dict[str, Any]]:
        return self._all(SQL_CATEGORY_BREAKDOWN, {"start_at": start_at})

    def severity_breakdown(self, start_at: Any) -> list[dict[str, Any]]:
        return self._all(SQL_SEVERITY_BREAKDOWN, {"start_at": start_at})

    def server_risk(self, start_at: Any) -> list[dict[str, Any]]:
        return self._all(SQL_SERVER_RISK, {"start_at": start_at})

    def decision_mix(self, start_at: Any) -> list[dict[str, Any]]:
        return self._all(SQL_DECISION_MIX, {"start_at": start_at})

    def workload_totals(self) -> dict[str, Any]:
        return self._one(SQL_WORKLOAD_TOTALS, {}) or {}

    def activity(self, limit: int = 12) -> list[dict[str, Any]]:
        return self._all(SQL_ACTIVITY_FEED, {"limit": max(1, min(limit, 100))})

    def dataset_summary(self) -> list[dict[str, Any]]:
        return self._all(SQL_DATASET_SUMMARY, {})
