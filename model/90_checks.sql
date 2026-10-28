-- Проверки после сборки. Если хоть одна не прошла, сборка падает
-- и вся транзакция откатывается: старая версия модели остаётся на месте.
--
-- Здесь только инварианты переноса (core совпадает с raw, витрины не теряют
-- и не размножают строки и деньги), а не контрольные цифры задания:
-- так проверки работают и на новых выгрузках.
-- Контрольные цифры проверяются отдельно: answers/99_controls.sql.

CREATE TEMP TABLE build_checks ON COMMIT DROP AS

-- 1. Перенос один-к-одному: ни одна строка не потеряна и не размножена.
SELECT 'строки: orders' AS check_name,
       (SELECT count(*) FROM raw.orders) = (SELECT count(*) FROM core.orders) AS ok
UNION ALL
SELECT 'строки: order_items',
       (SELECT count(*) FROM raw.order_items) = (SELECT count(*) FROM core.order_items)
UNION ALL
SELECT 'строки: order_payments',
       (SELECT count(*) FROM raw.order_payments) = (SELECT count(*) FROM core.order_payments)
UNION ALL
SELECT 'строки: order_reviews',
       (SELECT count(*) FROM raw.order_reviews) = (SELECT count(*) FROM core.order_reviews)
UNION ALL
SELECT 'строки: products',
       (SELECT count(*) FROM raw.products) = (SELECT count(*) FROM core.products)
UNION ALL
SELECT 'строки: sellers',
       (SELECT count(*) FROM raw.sellers) = (SELECT count(*) FROM core.sellers)
UNION ALL
SELECT 'строки: customers -> customer_order_profiles',
       (SELECT count(*) FROM raw.customers) = (SELECT count(*) FROM core.customer_order_profiles)
UNION ALL

-- 2. Люди: столько же, сколько уникальных customer_unique_id в источнике.
SELECT 'люди: customers = distinct customer_unique_id',
       (SELECT count(DISTINCT customer_unique_id) FROM raw.customers) = (SELECT count(*) FROM core.customers)
UNION ALL

-- 3. Категории: у каждого товара та же категория, что в источнике.
SELECT 'категории: совпадают с источником',
       NOT EXISTS (
           SELECT 1
           FROM raw.products r
           JOIN core.products p USING (product_id)
           WHERE p.category_key <> coalesce(r.product_category_name, '__unknown__')
       )
UNION ALL

-- 4. Деньги: число строк не защищает от искажения сумм, сверяем суммы.
SELECT 'суммы: price',
       (SELECT sum(price::numeric) FROM raw.order_items) = (SELECT sum(price) FROM core.order_items)
UNION ALL
SELECT 'суммы: freight_value',
       (SELECT sum(freight_value::numeric) FROM raw.order_items) = (SELECT sum(freight_value) FROM core.order_items)
UNION ALL
SELECT 'суммы: payment_value',
       (SELECT sum(payment_value::numeric) FROM raw.order_payments) = (SELECT sum(payment_value) FROM core.order_payments)
UNION ALL

-- 5. Витрина заказов: одна строка на заказ, дочерние строки не размножены.
SELECT 'order_totals: одна строка на заказ',
       (SELECT count(*) FROM mart.order_totals) = (SELECT count(*) FROM core.orders)
UNION ALL
SELECT 'order_totals: сумма товаров',
       (SELECT sum(goods_amount) FROM mart.order_totals) = (SELECT sum(price) FROM core.order_items)
UNION ALL
SELECT 'order_totals: сумма платежей',
       (SELECT sum(paid_amount) FROM mart.order_totals) = (SELECT sum(payment_value) FROM core.order_payments)
UNION ALL
SELECT 'order_totals: число платежей',
       (SELECT sum(payment_records) FROM mart.order_totals) = (SELECT count(*) FROM core.order_payments)
UNION ALL
SELECT 'order_totals: число отзывов',
       (SELECT sum(review_count) FROM mart.order_totals) = (SELECT count(*) FROM core.order_reviews)
UNION ALL

-- 6. Выручка одна и та же, как её ни разрезай: по позициям, продавцам,
-- категориям, месяцам. Если какой-то разрез теряет строки, суммы разойдутся.
SELECT 'выручка: delivered_items = позиции доставленных заказов',
       (SELECT sum(price) FROM mart.delivered_items) IS NOT DISTINCT FROM
       (SELECT sum(i.price)
        FROM core.order_items i
        JOIN core.orders o USING (order_id)
        WHERE o.status_code = 'delivered')
UNION ALL
SELECT 'выручка: по продавцам = общая',
       (SELECT sum(revenue) FROM mart.seller_sales) IS NOT DISTINCT FROM (SELECT sum(price) FROM mart.delivered_items)
UNION ALL
SELECT 'выручка: по категориям = общая',
       (SELECT sum(revenue) FROM mart.category_sales) IS NOT DISTINCT FROM (SELECT sum(price) FROM mart.delivered_items)
UNION ALL
SELECT 'выручка: по месяцам = общая',
       (SELECT sum(revenue) FROM mart.monthly_sales) = coalesce((SELECT sum(price) FROM mart.delivered_items), 0)
UNION ALL
SELECT 'выручка: по покупателям = общая',
       (SELECT sum(revenue) FROM mart.customers) IS NOT DISTINCT FROM (SELECT sum(price) FROM mart.delivered_items)
UNION ALL

-- 7. Покупатели: в витрине все люди, каждый по одному разу.
SELECT 'customers: одна строка на человека',
       (SELECT count(*) FROM mart.customers) = (SELECT count(*) FROM core.customers)
UNION ALL

-- 8. Календарь без дыр и покрывает все даты покупок.
SELECT 'календарь: без пропущенных дней',
       (SELECT count(*) FROM core.calendar) = (SELECT max(date) - min(date) + 1 FROM core.calendar)
UNION ALL
SELECT 'календарь: покрывает все покупки',
       NOT EXISTS (
           SELECT 1 FROM core.orders o
           WHERE NOT EXISTS (SELECT 1 FROM core.calendar c WHERE c.date = o.purchased_at::date)
       )
UNION ALL

-- Историчность: один адрес заказа, одна текущая категория, факт ссылается
-- на конкретную версию (её существование дополнительно гарантирует FK).
SELECT 'история: адрес для каждого заказа',
       (SELECT count(*) FROM core.order_addresses) = (SELECT count(*) FROM core.orders)
UNION ALL
SELECT 'история: текущая категория каждого товара',
       (SELECT count(*) FROM core.product_category_history WHERE observed_to IS NULL) =
       (SELECT count(*) FROM core.products)
       AND NOT EXISTS (SELECT 1 FROM core.products p
                       JOIN core.product_category_history h USING(product_id)
                       WHERE h.observed_to IS NULL AND h.category_key <> p.category_key)
UNION ALL

-- 9. Нет критических проблем качества (например, доставленного заказа без позиций).
SELECT 'качество: нет проблем уровня error',
       NOT EXISTS (SELECT 1 FROM mart.quality_issues WHERE severity = 'error');

-- Печатаем результат: непройденные проверки наверху.
SELECT check_name, CASE WHEN ok THEN 'OK' ELSE 'FAIL' END AS result
FROM build_checks
ORDER BY ok, check_name;

-- Сводка по проблемам качества: что есть в данных и сколько.
SELECT severity, issue_code, count(*) AS records
FROM mart.quality_issues
GROUP BY severity, issue_code
ORDER BY severity, issue_code;

-- Останавливаем сборку, если что-то не прошло.
DO $$
DECLARE
    failed text;
BEGIN
    SELECT string_agg(check_name, '; ') INTO failed
    FROM build_checks
    WHERE ok IS NOT TRUE;

    IF failed IS NOT NULL THEN
        RAISE EXCEPTION 'Проверки не пройдены: %', failed;
    END IF;
END $$;
