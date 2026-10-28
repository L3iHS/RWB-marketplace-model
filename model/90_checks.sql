-- Проверки после сборки. Если хоть одна не прошла, сборка падает
-- и вся транзакция откатывается: старая версия модели остаётся на месте.
--
-- Здесь только инварианты переноса (core совпадает с raw), а не контрольные
-- цифры задания: так проверки работают и на новых выгрузках.
-- Контрольные цифры проверяются отдельно, в answers/.

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
           JOIN core.categories c USING (category_id)
           WHERE c.name_pt IS DISTINCT FROM r.product_category_name
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

-- 5. Витрины не теряют и не размножают строки и деньги.
SELECT 'витрина order_totals: одна строка на заказ',
       (SELECT count(*) FROM mart.order_totals) = (SELECT count(*) FROM core.orders)
UNION ALL
SELECT 'витрина order_totals: сумма товаров',
       (SELECT sum(goods_amount) FROM mart.order_totals) = (SELECT sum(price) FROM core.order_items)
UNION ALL
SELECT 'витрина order_totals: сумма платежей',
       (SELECT sum(paid_amount) FROM mart.order_totals) = (SELECT sum(payment_value) FROM core.order_payments)
UNION ALL
SELECT 'витрина delivered_items: выручка = позиции доставленных заказов',
       (SELECT sum(price) FROM mart.delivered_items) =
       (SELECT sum(i.price)
        FROM core.order_items i
        JOIN core.orders o USING (order_id)
        WHERE o.status_code = 'delivered')
UNION ALL

-- 6. Календарь без дыр и покрывает все даты покупок.
SELECT 'календарь: без пропущенных дней',
       (SELECT count(*) FROM core.calendar) = (SELECT max(date) - min(date) + 1 FROM core.calendar)
UNION ALL
SELECT 'календарь: покрывает все покупки',
       NOT EXISTS (
           SELECT 1 FROM core.orders o
           WHERE NOT EXISTS (SELECT 1 FROM core.calendar c WHERE c.date = o.purchased_at::date)
       );

-- Печатаем результат: непройденные проверки наверху.
SELECT check_name, CASE WHEN ok THEN 'OK' ELSE 'FAIL' END AS result
FROM build_checks
ORDER BY ok, check_name;

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
