-- All data: intentionally independent of sales-period and buyer-state filters.
SELECT severity, issue_code, entity_type, COUNT(*) AS issues,
       COUNT(DISTINCT entity_id) AS affected_entities
FROM mart.quality_issues
GROUP BY severity, issue_code, entity_type
ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
         issues DESC, issue_code;