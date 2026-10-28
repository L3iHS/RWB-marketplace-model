-- Обычный SQL для DBeaver, без psql-команд \ir и \set.
-- Выполняйте SELECT по одному или весь файл как SQL script.
SELECT current_database() AS database_name, current_user AS username,
       current_schema() AS current_schema, current_setting('search_path') AS search_path;

SELECT table_schema, table_type, count(*) AS objects
FROM information_schema.tables
WHERE table_schema IN ('raw','core','mart') GROUP BY 1,2 ORDER BY 1,2;

SELECT 'raw.orders' AS entity, count(*) AS rows FROM raw.orders
UNION ALL SELECT 'core.orders', count(*) FROM core.orders
UNION ALL SELECT 'mart.order_totals', count(*) FROM mart.order_totals;

SELECT order_id, status_code, purchased_at, goods_amount, freight_amount,
       order_amount, paid_amount
FROM mart.order_totals ORDER BY purchased_at, order_id LIMIT 20;

SELECT issue_code, count(*) AS records FROM mart.quality_issues GROUP BY 1 ORDER BY 1;
