CREATE EXTERNAL TABLE IF NOT EXISTS claro_ods.message (
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
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
WITH SERDEPROPERTIES (
    'separatorChar'=',',
    'quoteChar'='"',
    'escapeChar'='\\',
    'serialization.null.format'='\\N'
)
STORED AS TEXTFILE
LOCATION '${hivevar:ods_root}/message'
TBLPROPERTIES ('skip.header.line.count'='1');

CREATE EXTERNAL TABLE IF NOT EXISTS claro_ods.risk_event (
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
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
WITH SERDEPROPERTIES (
    'separatorChar'=',',
    'quoteChar'='"',
    'escapeChar'='\\',
    'serialization.null.format'='\\N'
)
STORED AS TEXTFILE
LOCATION '${hivevar:ods_root}/risk_event'
TBLPROPERTIES ('skip.header.line.count'='1');

CREATE EXTERNAL TABLE IF NOT EXISTS claro_ods.policy_decision (
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
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
WITH SERDEPROPERTIES (
    'separatorChar'=',',
    'quoteChar'='"',
    'escapeChar'='\\',
    'serialization.null.format'='\\N'
)
STORED AS TEXTFILE
LOCATION '${hivevar:ods_root}/policy_decision'
TBLPROPERTIES ('skip.header.line.count'='1');

CREATE EXTERNAL TABLE IF NOT EXISTS claro_ods.moderation_record (
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
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
WITH SERDEPROPERTIES (
    'separatorChar'=',',
    'quoteChar'='"',
    'escapeChar'='\\',
    'serialization.null.format'='\\N'
)
STORED AS TEXTFILE
LOCATION '${hivevar:ods_root}/moderation_record'
TBLPROPERTIES ('skip.header.line.count'='1');
