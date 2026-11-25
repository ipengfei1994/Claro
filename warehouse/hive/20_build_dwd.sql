SET hive.exec.dynamic.partition=true;
SET hive.exec.dynamic.partition.mode=nonstrict;

CREATE TABLE IF NOT EXISTS claro_dwd.message_detail (
    message_id STRING,
    dataset_id STRING,
    dataset_name STRING,
    external_message_id STRING,
    sender_ref STRING,
    server_ref STRING,
    channel STRING,
    content STRING,
    content_hash STRING,
    language STRING,
    status STRING,
    occurred_at TIMESTAMP,
    ingested_at TIMESTAMP,
    is_synthetic BOOLEAN,
    source_updated_at TIMESTAMP
)
PARTITIONED BY (dt STRING)
STORED AS ORC;

CREATE TABLE IF NOT EXISTS claro_dwd.risk_detail (
    risk_event_id STRING,
    dataset_id STRING,
    dataset_name STRING,
    message_id STRING,
    rule_id STRING,
    category STRING,
    event_type STRING,
    risk_score DECIMAL(5,4),
    confidence DECIMAL(5,4),
    severity STRING,
    occurred_at TIMESTAMP,
    details_json STRING,
    is_synthetic BOOLEAN,
    source_updated_at TIMESTAMP
)
PARTITIONED BY (dt STRING)
STORED AS ORC;

CREATE TABLE IF NOT EXISTS claro_dwd.policy_decision_detail (
    decision_id STRING,
    dataset_id STRING,
    dataset_name STRING,
    message_id STRING,
    policy_id STRING,
    action STRING,
    risk_score DECIMAL(5,4),
    reason_codes_json STRING,
    decided_at TIMESTAMP,
    is_synthetic BOOLEAN,
    source_updated_at TIMESTAMP
)
PARTITIONED BY (dt STRING)
STORED AS ORC;

CREATE TABLE IF NOT EXISTS claro_dwd.moderation_record_detail (
    moderation_record_id STRING,
    dataset_id STRING,
    dataset_name STRING,
    message_id STRING,
    case_id STRING,
    idempotency_key STRING,
    action STRING,
    actor_type STRING,
    actor_ref STRING,
    risk_score DECIMAL(5,4),
    reason_codes_json STRING,
    note STRING,
    occurred_at TIMESTAMP,
    is_synthetic BOOLEAN,
    source_updated_at TIMESTAMP
)
PARTITIONED BY (dt STRING)
STORED AS ORC;

INSERT OVERWRITE TABLE claro_dwd.message_detail PARTITION (dt)
SELECT message_id, dataset_id, dataset_name, external_message_id, sender_ref,
       server_ref, channel, TRIM(content), content_hash, language, status,
       occurred_at, ingested_at, is_synthetic, source_updated_at, dt
FROM (
    SELECT m.*,
           ROW_NUMBER() OVER (PARTITION BY message_id ORDER BY source_updated_at DESC) AS rn
    FROM claro_ods.message m
    WHERE message_id IS NOT NULL AND occurred_at IS NOT NULL
) ranked
WHERE rn = 1;

INSERT OVERWRITE TABLE claro_dwd.risk_detail PARTITION (dt)
SELECT risk_event_id, dataset_id, dataset_name, message_id, rule_id, category,
       event_type, risk_score, confidence, severity, occurred_at, details_json,
       is_synthetic, source_updated_at, dt
FROM (
    SELECT r.*,
           ROW_NUMBER() OVER (PARTITION BY risk_event_id ORDER BY source_updated_at DESC) AS rn
    FROM claro_ods.risk_event r
    WHERE risk_event_id IS NOT NULL AND occurred_at IS NOT NULL
) ranked
WHERE rn = 1;

INSERT OVERWRITE TABLE claro_dwd.policy_decision_detail PARTITION (dt)
SELECT decision_id, dataset_id, dataset_name, message_id, policy_id, action,
       risk_score, reason_codes_json, decided_at, is_synthetic, source_updated_at, dt
FROM (
    SELECT p.*,
           ROW_NUMBER() OVER (PARTITION BY decision_id ORDER BY source_updated_at DESC) AS rn
    FROM claro_ods.policy_decision p
    WHERE decision_id IS NOT NULL AND decided_at IS NOT NULL
) ranked
WHERE rn = 1;

INSERT OVERWRITE TABLE claro_dwd.moderation_record_detail PARTITION (dt)
SELECT moderation_record_id, dataset_id, dataset_name, message_id, case_id,
       idempotency_key, action, actor_type, actor_ref, risk_score,
       reason_codes_json, note, occurred_at, is_synthetic, source_updated_at, dt
FROM (
    SELECT mr.*,
           ROW_NUMBER() OVER (
               PARTITION BY moderation_record_id ORDER BY source_updated_at DESC
           ) AS rn
    FROM claro_ods.moderation_record mr
    WHERE moderation_record_id IS NOT NULL AND occurred_at IS NOT NULL
) ranked
WHERE rn = 1;
