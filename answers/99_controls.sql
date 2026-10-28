-- Сверка ответов с контрольными цифрами из tasks.md.
-- Запуск: bash build.sh answers/99_controls.sql

WITH q1 AS (
    SELECT count(*)                          AS months,
           count(*) FILTER (WHERE revenue = 0) AS zero_months,
           sum(revenue)                      AS total
    FROM (
        SELECT m.month, coalesce(sum(d.price), 0) AS revenue
        FROM (SELECT DISTINCT month FROM core.calendar
              WHERE month BETWEEN '2016-09-01' AND '2018-08-01') m
        LEFT JOIN mart.delivered_items d ON d.purchase_month = m.month
        GROUP BY m.month
    ) t
), q2 AS (
    SELECT max(revenue) AS top_seller
    FROM (SELECT seller_id, sum(price) AS revenue FROM mart.delivered_items GROUP BY seller_id) t
), q3 AS (
    SELECT round(avg(order_amount), 2) AS avg_check
    FROM mart.order_totals WHERE is_delivered
), q4 AS (
    SELECT count(*) AS customers,
           round(100.0 * count(*) FILTER (WHERE n >= 2) / count(*), 2) AS returned_pct
    FROM (SELECT customer_unique_id, count(*) AS n FROM mart.order_totals GROUP BY 1) t
), q5 AS (
    SELECT count(*) AS categories, max(revenue) AS top_category, sum(revenue) AS total
    FROM (SELECT category_id, sum(price) AS revenue FROM mart.delivered_items GROUP BY 1) t
)
SELECT check_name, actual, expected, CASE WHEN actual = expected THEN 'OK' ELSE 'FAIL' END AS result
FROM (
    SELECT '1. месяцев'                 AS check_name, q1.months::text   AS actual, '24'          AS expected FROM q1
    UNION ALL SELECT '1. месяцев с нулём',          q1.zero_months::text,  '1'           FROM q1
    UNION ALL SELECT '1. выручка итого',            q1.total::text,        '13221498.11' FROM q1
    UNION ALL SELECT '2. первый продавец',          q2.top_seller::text,   '226987.93'   FROM q2
    UNION ALL SELECT '3. средний чек',              q3.avg_check::text,    '159.88'      FROM q3
    UNION ALL SELECT '4. покупателей',              q4.customers::text,    '96096'       FROM q4
    UNION ALL SELECT '4. вернулись, %',             q4.returned_pct::text, '3.12'        FROM q4
    UNION ALL SELECT '5. категорий',                q5.categories::text,   '74'          FROM q5
    UNION ALL SELECT '5. крупнейшая категория',     q5.top_category::text, '1233131.72'  FROM q5
    UNION ALL SELECT '5. сумма по категориям',      q5.total::text,        '13221498.11' FROM q5
) t;
