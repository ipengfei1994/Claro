SET hive.exec.dynamic.partition=true;
SET hive.exec.dynamic.partition.mode=nonstrict;

CREATE TABLE IF NOT EXISTS claro_dws.player_risk_daily (
    dt STRING,
    dataset_id STRING,
    dataset_name STRING,
    sender_ref STRING,
    server_ref STRING,
    total_messages BIGINT,
    risky_messages BIGINT,
    risk_events BIGINT,
    high_severity_events BIGINT,
    avg_risk_score DECIMAL(12,6),
    is_synthetic BOOLEAN
)
PARTITIONED BY (event_date STRING)
STORED AS ORC;

INSERT OVERWRITE TABLE claro_dws.player_risk_daily PARTITION (event_date=dt)
SELECT m.dt, m.dataset_id, m.dataset_name, m.sender_ref, m.server_ref,
       COUNT(DISTINCT m.message_id) AS total_messages,
       COUNT(DISTINCT r.message_id) AS risky_messages,
       COUNT(DISTINCT r.risk_event_id) AS risk_events,
       COUNT(DISTINCT CASE WHEN r.severity = 'high' THEN r.risk_event_id END)
           AS high_severity_events,
       AVG(r.risk_score) AS avg_risk_score,
       MAX(m.is_synthetic) AS is_synthetic
FROM claro_dwd.message_detail m
LEFT JOIN claro_dwd.risk_detail r
    ON r.message_id = m.message_id AND r.dt = m.dt
GROUP BY m.dt, m.dataset_id, m.dataset_name, m.sender_ref, m.server_ref, m.is_synthetic;

CREATE TABLE IF NOT EXISTS claro_ads.risk_overview_daily (
    event_date STRING,
    dataset_id STRING,
    dataset_name STRING,
    server_ref STRING,
    category STRING,
    total_messages BIGINT,
    risky_messages BIGINT,
    risk_events BIGINT,
    high_severity_events BIGINT,
    avg_risk_score DECIMAL(12,6),
    moderation_records BIGINT,
    is_synthetic BOOLEAN
)
PARTITIONED BY (dt STRING)
STORED AS ORC;

INSERT OVERWRITE TABLE claro_ads.risk_overview_daily PARTITION (dt)
SELECT r.event_date, r.dataset_id, r.dataset_name, r.server_ref, r.category,
       MAX(mc.total_messages) AS total_messages,
       SUM(r.risky_messages) AS risky_messages,
       SUM(r.risk_events) AS risk_events,
       SUM(r.high_severity_events) AS high_severity_events,
       AVG(r.avg_risk_score) AS avg_risk_score,
       COALESCE(SUM(mr.moderation_records), 0) AS moderation_records,
       MAX(r.is_synthetic) AS is_synthetic
FROM claro_dws.player_risk_daily r
JOIN (
    SELECT dt, dataset_id, server_ref, COUNT(DISTINCT message_id) AS total_messages
    FROM claro_dwd.message_detail
    GROUP BY dt, dataset_id, server_ref
) mc ON mc.dt = r.event_date AND mc.dataset_id = r.dataset_id
    AND mc.server_ref = r.server_ref
LEFT JOIN (
    SELECT mr.dt, mr.dataset_id, m.server_ref,
           COUNT(DISTINCT mr.moderation_record_id) AS moderation_records
    FROM claro_dwd.moderation_record_detail mr
    JOIN claro_dwd.message_detail m ON m.message_id = mr.message_id
    GROUP BY mr.dt, mr.dataset_id, m.server_ref
) mr ON mr.dt = r.event_date AND mr.dataset_id = r.dataset_id
    AND mr.server_ref = r.server_ref
WHERE r.risk_events > 0
GROUP BY r.event_date, r.dataset_id, r.dataset_name, r.server_ref, r.category;
