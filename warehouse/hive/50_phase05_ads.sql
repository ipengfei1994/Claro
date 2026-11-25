-- Phase 05 ADS layer design. NOT EXECUTED.
-- Status: Designed only. No Hive/Beeline is installed on this Windows host.
-- Do not treat these statements as verified Hive results.
-- KPI definitions must match docs/KPI_DEFINITIONS.md (phase-05.1).

-- 1. Risk daily report: message-level denominator, distinct risk messages.
INSERT OVERWRITE TABLE ads.risk_overview_daily PARTITION (dt = '${bizdate}')
SELECT
    '${bizdate}' AS stat_date,
    COUNT(DISTINCT m.message_id) AS total_messages,
    COUNT(DISTINCT CASE WHEN re.message_id IS NOT NULL THEN m.message_id END) AS risk_messages,
    COUNT(DISTINCT CASE WHEN re.severity IN ('high','critical') THEN m.message_id END) AS high_risk_messages,
    COUNT(DISTINCT CASE WHEN re.message_id IS NOT NULL THEN m.player_ref END) AS unique_risk_players
FROM dwd.message_detail m
LEFT JOIN dwd.risk_detail re ON re.message_id = m.message_id
WHERE m.dt = '${bizdate}';

-- 2. Server daily risk ranking.
INSERT OVERWRITE TABLE ads.server_risk_daily PARTITION (dt = '${bizdate}')
SELECT
    '${bizdate}' AS stat_date,
    m.server_ref,
    COUNT(DISTINCT m.message_id) AS total_messages,
    COUNT(DISTINCT CASE WHEN re.message_id IS NOT NULL THEN m.message_id END) AS risk_messages
FROM dwd.message_detail m
LEFT JOIN dwd.risk_detail re ON re.message_id = m.message_id
WHERE m.dt = '${bizdate}'
GROUP BY m.server_ref;

-- 3. Governance daily decisions.
INSERT OVERWRITE TABLE ads.governance_daily PARTITION (dt = '${bizdate}')
SELECT
    '${bizdate}' AS stat_date,
    decision_status,
    action,
    COUNT(DISTINCT decision_id) AS decision_count
FROM dwd.policy_decision_detail
WHERE dt = '${bizdate}'
GROUP BY decision_status, action;

-- 4. Policy hit detail from persisted evaluations.
INSERT OVERWRITE TABLE ads.policy_evaluation_daily PARTITION (dt = '${bizdate}')
SELECT
    '${bizdate}' AS stat_date,
    hit.policy_key,
    COUNT(DISTINCT pe.message_id) AS hit_messages
FROM dwd.policy_evaluation_detail pe
LATERAL VIEW explode(pe.matched_policies) matched AS hit
WHERE pe.dt = '${bizdate}'
GROUP BY hit.policy_key;

-- 5. Model performance from persisted evaluation runs (no metric recomputation).
INSERT OVERWRITE TABLE ads.model_performance_daily PARTITION (dt = '${bizdate}')
SELECT
    '${bizdate}' AS stat_date,
    model_id,
    dataset_name,
    split,
    metrics,
    per_label,
    created_at
FROM ods.evaluation_run
WHERE dt = '${bizdate}';
