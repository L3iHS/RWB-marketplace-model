-- Сверка ответов с контрольными цифрами из docs/tasks.md.
-- Цифры относятся только к выгрузке организаторов, поэтому живут здесь,
-- а не в проверках сборки (model/90_checks.sql).
-- Если хоть одна цифра не совпала, скрипт завершается ошибкой.
--
-- Запуск: bash build.sh answers/99_controls.sql   (или make check)

CREATE TEMP TABLE controls ON COMMIT DROP AS
WITH period AS (
    SELECT * FROM mart.monthly_sales
    WHERE month BETWEEN '2016-09-01' AND '2018-08-01'
)
SELECT '1. месяцев' AS check_name,
       (SELECT count(*) FROM period)::text AS actual, '24' AS expected
UNION ALL
SELECT '1. месяцев с нулевой выручкой',
       (SELECT count(*) FROM period WHERE revenue = 0)::text, '1'
UNION ALL
SELECT '1. выручка итого',
       (SELECT sum(revenue) FROM period)::text, '13221498.11'
UNION ALL
SELECT '2. первый продавец',
       (SELECT max(revenue) FROM mart.seller_sales)::text, '226987.93'
UNION ALL
SELECT '3. средний чек',
       (SELECT round(avg(order_amount), 2) FROM mart.order_totals WHERE is_delivered)::text, '159.88'
UNION ALL
SELECT '4. покупателей',
       (SELECT count(*) FROM mart.customers)::text, '96096'
UNION ALL
SELECT '4. вернулись, %',
       (SELECT round(100.0 * count(*) FILTER (WHERE orders >= 2) / count(*), 2) FROM mart.customers)::text, '3.12'
UNION ALL
SELECT '5. категорий',
       (SELECT count(*) FROM mart.category_sales)::text, '74'
UNION ALL
SELECT '5. крупнейшая категория',
       (SELECT max(revenue) FROM mart.category_sales)::text, '1233131.72'
UNION ALL
SELECT '5. сумма по категориям',
       (SELECT sum(revenue) FROM mart.category_sales)::text, '13221498.11';

SELECT check_name, actual, expected,
       CASE WHEN actual = expected THEN 'OK' ELSE 'FAIL' END AS result
FROM controls
ORDER BY check_name;

DO $$
DECLARE
    failed text;
BEGIN
    SELECT string_agg(check_name, '; ') INTO failed
    FROM controls
    WHERE actual IS DISTINCT FROM expected;

    IF failed IS NOT NULL THEN
        RAISE EXCEPTION 'Контрольные цифры не совпали: %', failed;
    END IF;
END $$;
