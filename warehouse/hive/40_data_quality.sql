SELECT 'ods_message_duplicates' AS check_name,
       COUNT(*) - COUNT(DISTINCT message_id) AS actual_value,
       0 AS expected_value,
       COUNT(*) = COUNT(DISTINCT message_id) AS passed
FROM claro_ods.message;

SELECT 'ods_risk_event_duplicates' AS check_name,
       COUNT(*) - COUNT(DISTINCT risk_event_id) AS actual_value,
       0 AS expected_value,
       COUNT(*) = COUNT(DISTINCT risk_event_id) AS passed
FROM claro_ods.risk_event;

SELECT 'invalid_content_hash' AS check_name,
       COUNT(*) AS actual_value,
       0 AS expected_value,
       COUNT(*) = 0 AS passed
FROM claro_dwd.message_detail
WHERE content_hash IS NULL OR LENGTH(content_hash) <> 64;

SELECT 'orphan_risk_events' AS check_name,
       COUNT(*) AS actual_value,
       0 AS expected_value,
       COUNT(*) = 0 AS passed
FROM claro_dwd.risk_detail r
LEFT JOIN claro_dwd.message_detail m ON m.message_id = r.message_id
WHERE m.message_id IS NULL;

SELECT 'missing_synthetic_marker' AS check_name,
       COUNT(*) AS actual_value,
       0 AS expected_value,
       COUNT(*) = 0 AS passed
FROM (
    SELECT is_synthetic FROM claro_dwd.message_detail
    UNION ALL
    SELECT is_synthetic FROM claro_dwd.risk_detail
    UNION ALL
    SELECT is_synthetic FROM claro_dwd.policy_decision_detail
    UNION ALL
    SELECT is_synthetic FROM claro_dwd.moderation_record_detail
) marked
WHERE is_synthetic IS NULL;

SELECT 'message_dwd_reconciliation' AS check_name,
       ABS((SELECT COUNT(DISTINCT message_id) FROM claro_ods.message)
           - (SELECT COUNT(*) FROM claro_dwd.message_detail)) AS actual_value,
       0 AS expected_value,
       (SELECT COUNT(DISTINCT message_id) FROM claro_ods.message)
           = (SELECT COUNT(*) FROM claro_dwd.message_detail) AS passed;

SELECT 'risk_dwd_reconciliation' AS check_name,
       ABS((SELECT COUNT(DISTINCT risk_event_id) FROM claro_ods.risk_event)
           - (SELECT COUNT(*) FROM claro_dwd.risk_detail)) AS actual_value,
       0 AS expected_value,
       (SELECT COUNT(DISTINCT risk_event_id) FROM claro_ods.risk_event)
           = (SELECT COUNT(*) FROM claro_dwd.risk_detail) AS passed;
