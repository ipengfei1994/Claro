"""Centralised, parameterised SQL for Phase 05 analytics.

Every query is executed against PostgreSQL through AnalyticsRepository. The
shared ``scoped`` CTE guarantees that denominators and numerators use the same
message set and the same half-open time window.

PostgreSQL-specific syntax is intentional: this project's authoritative
database is PostgreSQL, and these queries are exercised by integration tests
against the real service.
"""

from __future__ import annotations

from typing import Literal

Grain = Literal["hour", "day", "week", "month"]

SCOPED_CTE = """
WITH scoped AS (
    SELECT m.id, m.player_id, m.server_id, m.alliance_id, m.server_ref,
           m.sender_ref, m.occurred_at, m.dataset_id, m.content_hash,
           m.channel, m.language
    FROM message m
    LEFT JOIN dataset d ON d.id = m.dataset_id
    LEFT JOIN alliance a ON a.id = m.alliance_id
    WHERE m.occurred_at >= :start AND m.occurred_at < :end
      AND (CAST(:dataset_id AS uuid) IS NULL OR m.dataset_id = :dataset_id)
      AND (CAST(:dataset_name AS text) IS NULL OR d.name = :dataset_name)
      AND (CAST(:server_ref AS text) IS NULL OR m.server_ref = :server_ref)
      AND (CAST(:alliance_ref AS text) IS NULL OR a.alliance_ref = :alliance_ref)
      AND (CAST(:player_ref AS text) IS NULL OR m.sender_ref = :player_ref)
),
risk AS (
    SELECT DISTINCT re.message_id
    FROM risk_event re
    JOIN scoped s ON s.id = re.message_id
    WHERE (CAST(:risk_category AS text) IS NULL OR re.category = :risk_category)
      AND (CAST(:risk_severity AS text) IS NULL OR re.severity = :risk_severity)
),
high_risk AS (
    SELECT DISTINCT re.message_id
    FROM risk_event re
    JOIN scoped s ON s.id = re.message_id
    WHERE re.severity IN ('high', 'critical')
      AND (CAST(:risk_category AS text) IS NULL OR re.category = :risk_category)
)
"""

SQL_OVERVIEW = SCOPED_CTE + """
SELECT COUNT(DISTINCT s.id) AS total_messages,
       COUNT(DISTINCT r.message_id) AS risk_messages,
       COUNT(DISTINCT h.message_id) AS high_risk_messages,
       COUNT(DISTINCT s.player_id) AS active_players,
       COUNT(DISTINCT s.server_ref) AS active_servers,
       COUNT(DISTINCT s.player_id) FILTER (WHERE r.message_id IS NOT NULL) AS unique_risk_players,
       MIN(s.occurred_at) AS first_message_at,
       MAX(s.occurred_at) AS last_message_at
FROM scoped s
LEFT JOIN risk r ON r.message_id = s.id
LEFT JOIN high_risk h ON h.message_id = s.id
"""

SQL_REPEAT_OFFENDERS = SCOPED_CTE + """
SELECT COUNT(*) AS repeat_offenders
FROM (
    SELECT s.player_id, COUNT(DISTINCT r.message_id) AS risk_messages
    FROM scoped s
    JOIN risk r ON r.message_id = s.id
    WHERE s.player_id IS NOT NULL
    GROUP BY s.player_id
    HAVING COUNT(DISTINCT r.message_id) >= CAST(:repeat_threshold AS int)
) offenders
"""


def daily_counts_sql(grain: Grain) -> str:
    """Return the time-bucketed message/risk query for a whitelisted grain."""
    if grain not in ("hour", "day", "week", "month"):
        raise ValueError(f"unsupported grain: {grain}")
    return SCOPED_CTE + f"""
SELECT date_trunc('{grain}', s.occurred_at) AS bucket,
       COUNT(DISTINCT s.id) AS total_messages,
       COUNT(DISTINCT r.message_id) AS risk_messages,
       COUNT(DISTINCT h.message_id) AS high_risk_messages
FROM scoped s
LEFT JOIN risk r ON r.message_id = s.id
LEFT JOIN high_risk h ON h.message_id = s.id
GROUP BY 1
ORDER BY 1
"""


SQL_CATEGORY_DISTRIBUTION = SCOPED_CTE + """
SELECT re.category,
       COUNT(DISTINCT re.message_id) AS message_count,
       COUNT(*) AS event_count,
       AVG(re.risk_score) AS avg_score
FROM risk_event re
JOIN scoped s ON s.id = re.message_id
WHERE (CAST(:risk_category AS text) IS NULL OR re.category = :risk_category)
  AND (CAST(:risk_severity AS text) IS NULL OR re.severity = :risk_severity)
GROUP BY re.category
ORDER BY message_count DESC
"""

SQL_SEVERITY_DISTRIBUTION = SCOPED_CTE.rstrip() + """
, ranked AS (
    SELECT re.message_id, re.severity,
           ROW_NUMBER() OVER (
               PARTITION BY re.message_id
               ORDER BY CASE re.severity
                   WHEN 'critical' THEN 5 WHEN 'high' THEN 4 WHEN 'medium' THEN 3
                   WHEN 'low' THEN 2 ELSE 1 END DESC, re.risk_score DESC
           ) AS rn
    FROM risk_event re
    JOIN scoped s ON s.id = re.message_id
    WHERE (CAST(:risk_category AS text) IS NULL OR re.category = :risk_category)
      AND (CAST(:risk_severity AS text) IS NULL OR re.severity = :risk_severity)
)
SELECT severity, COUNT(*) AS message_count
FROM ranked
WHERE rn = 1
GROUP BY severity
ORDER BY message_count DESC
"""

SQL_COOCCURRENCE = SCOPED_CTE + """
SELECT a.category AS category_a, b.category AS category_b,
       COUNT(DISTINCT a.message_id) AS message_count
FROM risk_event a
JOIN risk_event b ON b.message_id = a.message_id AND b.category > a.category
JOIN scoped s ON s.id = a.message_id
WHERE (CAST(:risk_category AS text) IS NULL
       OR a.category = :risk_category OR b.category = :risk_category)
GROUP BY a.category, b.category
ORDER BY message_count DESC
"""

SQL_SERVER_RANKING = SCOPED_CTE + """
, decisions AS (
    SELECT s.server_ref,
           COUNT(*) AS total_decisions,
           COUNT(*) FILTER (WHERE pd.decision_status = 'auto_decided') AS auto_decided,
           COUNT(*) FILTER (WHERE pd.decision_status IN
               ('pending_review', 'human_reviewed', 'overridden')) AS review_decisions,
           COUNT(*) FILTER (WHERE pd.decision_status IS NOT NULL) AS status_decisions
    FROM policy_decision pd
    JOIN scoped s ON s.id = pd.message_id
    GROUP BY s.server_ref
)
SELECT s.server_ref,
       COALESCE(sv.name, s.server_ref) AS server_name,
       sv.region,
       COUNT(DISTINCT s.id) AS total_messages,
       COUNT(DISTINCT r.message_id) AS risk_messages,
       COUNT(DISTINCT h.message_id) AS high_risk_messages,
       COUNT(DISTINCT s.player_id) AS active_players,
       COUNT(DISTINCT s.player_id) FILTER (WHERE r.message_id IS NOT NULL) AS risk_players,
       COALESCE(d.total_decisions, 0) AS total_decisions,
       COALESCE(d.auto_decided, 0) AS auto_decided,
       COALESCE(d.review_decisions, 0) AS review_decisions,
       COALESCE(d.status_decisions, 0) AS status_decisions
FROM scoped s
LEFT JOIN server sv ON sv.server_ref = s.server_ref AND sv.dataset_id = s.dataset_id
LEFT JOIN risk r ON r.message_id = s.id
LEFT JOIN high_risk h ON h.message_id = s.id
LEFT JOIN decisions d ON d.server_ref = s.server_ref
GROUP BY s.server_ref, server_name, sv.region,
         d.total_decisions, d.auto_decided, d.review_decisions, d.status_decisions
ORDER BY risk_messages DESC
"""

SQL_ALLIANCE_RANKING = SCOPED_CTE + """
, decisions AS (
    SELECT s.alliance_id,
           COUNT(*) AS total_decisions,
           COUNT(*) FILTER (WHERE pd.decision_status = 'auto_decided') AS auto_decided
    FROM policy_decision pd
    JOIN scoped s ON s.id = pd.message_id
    WHERE s.alliance_id IS NOT NULL
    GROUP BY s.alliance_id
)
SELECT a.alliance_ref, COALESCE(a.name, a.alliance_ref) AS alliance_name,
       a.server_ref,
       COUNT(DISTINCT s.id) AS total_messages,
       COUNT(DISTINCT r.message_id) AS risk_messages,
       COUNT(DISTINCT h.message_id) AS high_risk_messages,
       COUNT(DISTINCT s.player_id) AS active_players,
       COUNT(DISTINCT s.player_id) FILTER (WHERE h.message_id IS NOT NULL) AS high_risk_players,
       COALESCE(d.total_decisions, 0) AS total_decisions,
       COALESCE(d.auto_decided, 0) AS auto_decided
FROM scoped s
LEFT JOIN alliance a ON a.id = s.alliance_id
LEFT JOIN risk r ON r.message_id = s.id
LEFT JOIN high_risk h ON h.message_id = s.id
LEFT JOIN decisions d ON d.alliance_id = s.alliance_id
WHERE s.alliance_id IS NOT NULL
GROUP BY a.alliance_ref, alliance_name, a.server_ref,
         d.total_decisions, d.auto_decided
ORDER BY risk_messages DESC
"""

SQL_PLAYER_PROFILE = SCOPED_CTE + """
, risk_times AS (
    SELECT re.message_id, MAX(re.occurred_at) AS last_risk_at
    FROM risk_event re
    JOIN scoped s ON s.id = re.message_id
    GROUP BY re.message_id
),
decisions AS (
    SELECT s.sender_ref,
           COUNT(*) AS decision_count,
           COUNT(*) FILTER (WHERE pd.action IN
               ('block', 'mute', 'temp_ban', 'perm_ban', 'restrict')) AS restrictive_count
    FROM policy_decision pd
    JOIN scoped s ON s.id = pd.message_id
    GROUP BY s.sender_ref
),
sanctions AS (
    SELECT ea.target_ref, COUNT(*) AS sanction_count
    FROM enforcement_action ea
    WHERE ea.target_type = 'player'
    GROUP BY ea.target_ref
)
SELECT s.sender_ref,
       MIN(s.player_id::text) AS player_id,
       COUNT(DISTINCT s.id) AS total_messages,
       COUNT(DISTINCT r.message_id) AS risk_messages,
       MAX(rt.last_risk_at) AS last_risk_at,
       COALESCE(d.decision_count, 0) AS decision_count,
       COALESCE(d.restrictive_count, 0) AS restrictive_count,
       COALESCE(san.sanction_count, 0) AS sanction_count
FROM scoped s
LEFT JOIN risk r ON r.message_id = s.id
LEFT JOIN risk_times rt ON rt.message_id = s.id
LEFT JOIN decisions d ON d.sender_ref = s.sender_ref
LEFT JOIN sanctions san ON san.target_ref = s.sender_ref
GROUP BY s.sender_ref, d.decision_count, d.restrictive_count, san.sanction_count
ORDER BY risk_messages DESC, total_messages DESC
LIMIT :limit
"""

SQL_GOVERNANCE_TOTALS = SCOPED_CTE + """
SELECT COUNT(*) AS total_decisions,
       COUNT(DISTINCT pd.message_id) AS decided_messages,
       COUNT(*) FILTER (WHERE pd.decision_status IS NOT NULL
           AND pd.decision_status <> 'cancelled') AS eligible_finalized,
       COUNT(*) FILTER (WHERE pd.decision_status = 'auto_decided') AS auto_decided,
       COUNT(*) FILTER (WHERE pd.decision_status IN
           ('pending_review', 'human_reviewed', 'overridden')) AS review_decisions,
       COUNT(*) FILTER (WHERE pd.decision_status = 'human_reviewed') AS human_reviewed,
       COUNT(*) FILTER (WHERE pd.decision_status = 'overridden') AS overridden,
       COUNT(*) FILTER (WHERE pd.requires_review IS TRUE) AS flagged_for_review,
       COUNT(*) FILTER (WHERE pd.policy_evaluation_id IS NOT NULL) AS linked_evaluations
FROM policy_decision pd
JOIN scoped s ON s.id = pd.message_id
"""

SQL_DECISION_DISTRIBUTION = SCOPED_CTE + """
SELECT pd.action, COALESCE(pd.decision_status, 'legacy_unset') AS decision_status,
       COUNT(*) AS decision_count,
       COUNT(DISTINCT pd.message_id) AS message_count
FROM policy_decision pd
JOIN scoped s ON s.id = pd.message_id
GROUP BY pd.action, decision_status
ORDER BY decision_count DESC
"""

SQL_MODERATION_TOTALS = SCOPED_CTE + """
, reviews AS (
    SELECT mc.id AS case_id,
           COUNT(mr.id) AS review_count,
           COUNT(*) FILTER (WHERE mr.action = 'override') AS override_count
    FROM moderation_case mc
    LEFT JOIN moderation_review mr ON mr.case_id = mc.id
    GROUP BY mc.id
)
SELECT COUNT(*) AS total_tasks,
       COUNT(*) FILTER (WHERE mc.closed_at IS NOT NULL) AS completed_tasks,
       COUNT(*) FILTER (WHERE mc.status IN
           ('open', 'pending', 'in_review', 'second_review', 'escalated')) AS pending_tasks,
       COUNT(*) FILTER (WHERE mc.required_second_review) AS second_review_tasks,
       COUNT(*) FILTER (WHERE mc.decision_id IS NOT NULL) AS linked_decisions,
       COUNT(*) FILTER (WHERE mc.closed_at IS NOT NULL
           AND mc.closed_at >= mc.opened_at) AS valid_durations,
       AVG(EXTRACT(EPOCH FROM (mc.closed_at - mc.opened_at)))
           FILTER (WHERE mc.closed_at IS NOT NULL AND mc.closed_at >= mc.opened_at) AS avg_seconds,
       percentile_cont(0.5) WITHIN GROUP (
           ORDER BY EXTRACT(EPOCH FROM (mc.closed_at - mc.opened_at)))
           FILTER (WHERE mc.closed_at IS NOT NULL AND mc.closed_at >= mc.opened_at) AS p50_seconds,
       percentile_cont(0.9) WITHIN GROUP (
           ORDER BY EXTRACT(EPOCH FROM (mc.closed_at - mc.opened_at)))
           FILTER (WHERE mc.closed_at IS NOT NULL AND mc.closed_at >= mc.opened_at) AS p90_seconds,
       COALESCE(SUM(rv.review_count), 0) AS review_count,
       COALESCE(SUM(rv.override_count), 0) AS override_count
FROM moderation_case mc
JOIN scoped s ON s.id = mc.message_id
LEFT JOIN reviews rv ON rv.case_id = mc.id
"""

SQL_MODERATION_BY_STATUS = SCOPED_CTE + """
SELECT mc.status, COALESCE(mc.resolution, 'unset') AS resolution, COUNT(*) AS task_count,
       COUNT(*) FILTER (WHERE mc.closed_at IS NOT NULL) AS completed
FROM moderation_case mc
JOIN scoped s ON s.id = mc.message_id
GROUP BY mc.status, resolution
ORDER BY task_count DESC
"""

SQL_ENFORCEMENT_DISTRIBUTION = SCOPED_CTE + """
SELECT ea.action_type, ea.status, ea.simulated,
       COUNT(*) AS action_count,
       COUNT(DISTINCT ea.target_ref) AS target_count,
       AVG(ea.duration_seconds) AS avg_duration_seconds,
       COUNT(*) FILTER (WHERE ea.expires_at IS NOT NULL) AS with_expiry,
       COUNT(*) FILTER (WHERE ea.released_at IS NOT NULL) AS released_count,
       COUNT(DISTINCT pd.message_id) FILTER (
           WHERE re.category IS NOT NULL) AS messages_with_risk_category
FROM enforcement_action ea
JOIN policy_decision pd ON pd.id = ea.decision_id
JOIN scoped s ON s.id = pd.message_id
LEFT JOIN risk_event re ON re.message_id = pd.message_id
GROUP BY ea.action_type, ea.status, ea.simulated
ORDER BY action_count DESC
"""

SQL_MODEL_RUNS = """
SELECT er.id AS run_id, er.model_id, er.dataset_name, er.split, er.message_count,
       er.metrics, er.per_label, er.case_counts, er.leakage, er.created_at,
       mm.name AS model_name, mm.version AS model_version, mm.algorithm,
       mm.training_params, mm.thresholds
FROM evaluation_run er
JOIN ml_model mm ON mm.id = er.model_id
WHERE (CAST(:model_id AS text) IS NULL OR er.model_id = :model_id)
ORDER BY er.created_at DESC
"""

SQL_MODEL_ERROR_CASES = SCOPED_CTE + """
SELECT ec.error_type, COALESCE(ec.category, 'unspecified') AS category,
       ec.truth_label, COUNT(*) AS case_count,
       AVG(ec.predicted_score) AS avg_predicted_score
FROM evaluation_case ec
LEFT JOIN scoped s ON s.id = ec.message_id
WHERE (CAST(:risk_category AS text) IS NULL OR ec.category = :risk_category)
GROUP BY ec.error_type, category, ec.truth_label
ORDER BY case_count DESC
"""

SQL_OBSERVED_RISK_VS_LABEL = SCOPED_CTE + """
SELECT rr.message_id, rr.risk_score, rr.risk_level, rr.categories, rr.detected_at,
       ml.label AS truth_label, ml.risk_category AS truth_category, ml.split
FROM risk_result rr
JOIN scoped s ON s.id = rr.message_id
LEFT JOIN message_label ml ON ml.message_id = rr.message_id
ORDER BY rr.detected_at DESC
"""

SQL_POLICY_HITS = SCOPED_CTE + """
, hits AS (
    SELECT pe.message_id, hit.item ->> 'policy_key' AS policy_key,
           (hit.item ->> 'version')::int AS policy_version,
           hit.item ->> 'action' AS action
    FROM policy_evaluation pe
    CROSS JOIN LATERAL jsonb_array_elements(pe.matched_policies) AS hit(item)
    JOIN scoped s ON s.id = pe.message_id
),
hit_counts AS (
    SELECT policy_key, COUNT(DISTINCT message_id) AS replay_hit_messages
    FROM hits
    GROUP BY policy_key
),
evaluated AS (
    SELECT COUNT(DISTINCT pe.message_id) AS evaluated_messages,
           COUNT(DISTINCT pe.message_id) FILTER (
               WHERE pe.suggested_action <> 'allow') AS restrictive_suggestions,
           COUNT(DISTINCT pe.message_id) FILTER (
               WHERE pe.suggested_action = 'review') AS review_suggestions
    FROM policy_evaluation pe
    JOIN scoped s ON s.id = pe.message_id
)
SELECT p.policy_key, p.id AS policy_id, p.version AS current_version,
       p.hit_count AS cumulative_hit_count, p.action AS configured_action,
       COALESCE(hc.replay_hit_messages, 0) AS replay_hit_messages,
       COALESCE(e.evaluated_messages, 0) AS evaluated_messages,
       COALESCE(e.restrictive_suggestions, 0) AS restrictive_suggestions,
       COALESCE(e.review_suggestions, 0) AS review_suggestions
FROM policy p
LEFT JOIN hit_counts hc ON hc.policy_key = p.policy_key
LEFT JOIN evaluated e ON TRUE
WHERE (CAST(:policy_key AS text) IS NULL OR p.policy_key = :policy_key)
  AND p.version > 0
ORDER BY replay_hit_messages DESC, cumulative_hit_count DESC
"""

SQL_POLICY_EVALUATION_ACTIONS = SCOPED_CTE + """
SELECT pe.suggested_action,
       COUNT(DISTINCT pe.message_id) AS message_count,
       COUNT(*) AS evaluation_count,
       COUNT(DISTINCT pd.id) FILTER (WHERE pd.decision_status = 'overridden') AS overridden
FROM policy_evaluation pe
JOIN scoped s ON s.id = pe.message_id
LEFT JOIN policy_decision pd ON pd.policy_evaluation_id = pe.id
GROUP BY pe.suggested_action
ORDER BY message_count DESC
"""

SQL_REPLAY_INPUT = SCOPED_CTE.rstrip() + """
, latest_risk AS (
    SELECT DISTINCT ON (re.message_id)
           re.message_id, re.category, re.risk_score, re.severity, re.confidence
    FROM risk_event re
    JOIN scoped s ON s.id = re.message_id
    ORDER BY re.message_id, re.occurred_at DESC, re.risk_score DESC
)
SELECT s.id AS message_id, m.content, s.content_hash, s.channel, s.language, s.sender_ref,
       s.server_ref, s.alliance_id::text AS alliance_id,
       lr.category, lr.risk_score, lr.severity, lr.confidence,
       ml.label AS truth_label
FROM scoped s
JOIN message m ON m.id = s.id
JOIN latest_risk lr ON lr.message_id = s.id
LEFT JOIN message_label ml ON ml.message_id = s.id
ORDER BY s.id
LIMIT :limit
"""

SQL_REPLAY_RUNS = """
SELECT run_id, created_at, dataset_name, window_start, window_end, baseline_label,
       candidate_label, sample_count, definition_version, parameters, simulation
FROM analytics_replay_run
ORDER BY created_at DESC
LIMIT :limit
"""

SQL_REPLAY_DIFF = """
SELECT c.message_id, c.baseline_hit, c.candidate_hit, c.baseline_action,
       c.candidate_action, c.diff_type, c.truth_label, c.baseline_fp, c.baseline_fn,
       c.candidate_fp, c.candidate_fn
FROM analytics_replay_case c
WHERE c.run_id = :run_id
ORDER BY c.message_id
"""

SQL_REPLAY_SUMMARY = """
SELECT r.run_id, r.created_at, r.sample_count, r.baseline_label, r.candidate_label,
       COUNT(c.message_id) AS case_count,
       COUNT(*) FILTER (WHERE c.baseline_hit) AS baseline_hits,
       COUNT(*) FILTER (WHERE c.candidate_hit) AS candidate_hits,
       COUNT(*) FILTER (WHERE c.diff_type = 'added_hit') AS added_hits,
       COUNT(*) FILTER (WHERE c.diff_type = 'removed_hit') AS removed_hits,
       COUNT(*) FILTER (WHERE c.diff_type IN ('stricter', 'looser', 'changed')) AS action_changes,
       COUNT(*) FILTER (WHERE c.baseline_action = 'review') AS baseline_reviews,
       COUNT(*) FILTER (WHERE c.candidate_action = 'review') AS candidate_reviews,
       COALESCE(SUM(c.baseline_fp::int), 0) AS baseline_fp,
       COALESCE(SUM(c.baseline_fn::int), 0) AS baseline_fn,
       COALESCE(SUM(c.candidate_fp::int), 0) AS candidate_fp,
       COALESCE(SUM(c.candidate_fn::int), 0) AS candidate_fn
FROM analytics_replay_run r
LEFT JOIN analytics_replay_case c ON c.run_id = r.run_id
WHERE (CAST(:run_id AS uuid) IS NULL OR r.run_id = :run_id)
GROUP BY r.run_id, r.created_at, r.sample_count, r.baseline_label, r.candidate_label
ORDER BY r.created_at DESC
LIMIT :limit
"""

SQL_DQ_ORPHANS = """
SELECT
 (SELECT COUNT(*) FROM risk_event re LEFT JOIN message m ON m.id = re.message_id
   WHERE m.id IS NULL) AS risk_event_orphans,
 (SELECT COUNT(*) FROM policy_decision pd LEFT JOIN message m ON m.id = pd.message_id
   WHERE m.id IS NULL) AS decision_orphans,
 (SELECT COUNT(*) FROM enforcement_action ea
   LEFT JOIN policy_decision pd ON pd.id = ea.decision_id
   WHERE pd.id IS NULL) AS enforcement_orphans
"""

SQL_DQ_DUPLICATES = """
SELECT
 (SELECT COUNT(*) - COUNT(DISTINCT id) FROM message) AS duplicate_message_ids,
 (SELECT COUNT(*) - COUNT(DISTINCT external_message_id) FROM message) AS duplicate_external_ids,
 (SELECT COUNT(*) FROM (
    SELECT message_id, rule_id, category, occurred_at
    FROM risk_event
    GROUP BY message_id, rule_id, category, occurred_at HAVING COUNT(*) > 1
  ) duplicates) AS duplicate_risk_events
"""

SQL_DQ_COVERAGE = """
SELECT
 (SELECT COUNT(*) FROM message) AS messages,
 (SELECT COUNT(DISTINCT message_id) FROM risk_result) AS risk_result_messages,
 (SELECT COUNT(*) FROM policy_decision WHERE policy_evaluation_id IS NOT NULL) AS linked_decisions,
 (SELECT COUNT(*) FROM policy_decision) AS decisions,
 (SELECT COUNT(*) FROM moderation_case WHERE decision_id IS NOT NULL) AS linked_cases,
 (SELECT COUNT(*) FROM moderation_case) AS cases,
 (SELECT COUNT(*) FROM moderation_review) AS reviews,
 (SELECT COUNT(*) FROM governance_feedback) AS feedback
"""

SQL_DQ_TIME = """
SELECT
 (SELECT COUNT(*) FROM message
   WHERE occurred_at IS NULL OR ingested_at IS NULL) AS invalid_message_time,
 (SELECT COUNT(*) FROM moderation_case
   WHERE closed_at IS NOT NULL AND closed_at < opened_at) AS invalid_case_time,
  (SELECT percentile_cont(0.95) WITHIN GROUP (
      ORDER BY EXTRACT(EPOCH FROM (ingested_at - occurred_at)))
   FROM message) AS ingest_lag_p95_seconds
"""

SQL_DATASET_INFO = """
SELECT id, name, seed, is_synthetic, generation_params, created_at
FROM dataset
ORDER BY created_at
"""
