-- Витрины mart: готовые наборы для отчётов поверх core.
-- Это представления (view): они не хранят данные, а пересчитываются из core
-- при каждом запросе, поэтому не могут разойтись с моделью.
--
-- Правило про пустые значения:
--   * количества (единиц, платежей, отзывов) при отсутствии строк — 0,
--     потому что «ни одной строки» — это известный факт;
--   * денежные суммы при отсутствии строк — NULL: если у заказа нет позиций,
--     мы не знаем, сколько он стоил, и не выдаём неизвестное за ноль.

-- Один заказ = одна строка, с итогами по позициям, платежам и отзывам.
--
-- Главное правило: позиции, платежи и отзывы сначала сворачиваем до уровня
-- заказа каждый отдельно, и только потом присоединяем к заказу. Если соединить
-- их напрямую, строки перемножатся: заказ с двумя товарами (100 и 50)
-- и двумя платежами (120 и 30) даст 4 строки, и товары посчитаются
-- как 300 вместо 150.
CREATE VIEW mart.order_totals AS
WITH items AS (
    SELECT order_id,
           count(*)                                AS units,           -- единиц товара
           count(DISTINCT (product_id, seller_id)) AS lines,           -- строк чека: товар + продавец
           count(DISTINCT seller_id)               AS sellers,
           sum(price)                              AS goods_amount,    -- товары без доставки
           sum(freight_value)                      AS freight_amount,
           sum(price + freight_value)              AS order_amount     -- чек: товары + доставка
    FROM core.order_items
    GROUP BY order_id
), payments AS (
    SELECT order_id,
           count(*)           AS payment_records,
           sum(payment_value) AS paid_amount
    FROM core.order_payments
    GROUP BY order_id
), reviews AS (
    -- Последний отзыв заказа: по времени ответа, затем по времени создания.
    -- review_id в конце сортировки делает выбор однозначным при равных датах.
    SELECT DISTINCT ON (order_id)
           order_id,
           count(*) OVER (PARTITION BY order_id) AS review_count,
           score                                 AS latest_review_score
    FROM core.order_reviews
    ORDER BY order_id, answered_at DESC NULLS LAST, created_at DESC NULLS LAST, review_id
)
SELECT o.order_id,
       p.customer_unique_id,
       o.customer_id,
       p.city  AS customer_city,
       p.state AS customer_state,
       o.status_code,
       s.is_delivered,
       o.purchased_at,
       date_trunc('month', o.purchased_at)::date AS purchase_month,
       o.approved_at,
       o.delivered_carrier_at,
       o.delivered_customer_at,
       o.estimated_delivery_at,
       -- Сроки считаем по календарным датам и только когда известны обе даты.
       -- Обещанная дата в источнике без времени, поэтому сравниваем даты, а не timestamp.
       o.delivered_customer_at::date - o.purchased_at::date          AS delivery_days,
       o.delivered_customer_at::date - o.estimated_delivery_at::date AS delay_days,  -- > 0 — опоздание
       o.delivered_customer_at::date > o.estimated_delivery_at::date AS is_late,
       coalesce(i.units, 0)   AS units,
       coalesce(i.lines, 0)   AS lines,
       coalesce(i.sellers, 0) AS sellers,
       i.goods_amount,
       i.freight_amount,
       i.order_amount,
       coalesce(pay.payment_records, 0) AS payment_records,
       pay.paid_amount,
       pay.paid_amount - i.order_amount AS payment_delta,  -- платежи минус чек
       coalesce(r.review_count, 0) AS review_count,
       r.latest_review_score
FROM core.orders o
JOIN core.order_statuses s USING (status_code)
JOIN core.customer_order_profiles p USING (customer_id)
LEFT JOIN items i USING (order_id)
LEFT JOIN payments pay USING (order_id)
LEFT JOIN reviews r USING (order_id);

-- Одна строка = одна единица товара доставленного заказа.
-- Здесь применяется правило выручки: выручка = сумма price этих строк.
-- Уровень позиции позволяет делить выручку по продавцам и категориям
-- без распределения суммы заказа: у каждой позиции свой продавец и товар.
CREATE VIEW mart.delivered_items AS
SELECT i.order_id,
       i.order_item_id,
       i.product_id,
       i.seller_id,
       pr.category_key,
       i.price,
       i.freight_value,
       o.purchased_at,
       date_trunc('month', o.purchased_at)::date AS purchase_month,
       p.customer_unique_id
FROM core.order_items i
JOIN core.orders o USING (order_id)
JOIN core.order_statuses s USING (status_code)
JOIN core.products pr USING (product_id)
JOIN core.customer_order_profiles p USING (customer_id)
WHERE s.is_delivered;

-- Один месяц календаря = одна строка: доставленные заказы и выручка.
-- Строим от календаря, поэтому месяц без продаж есть в витрине с нулём.
-- Здесь ноль настоящий: продаж в этом месяце точно не было.
CREATE VIEW mart.monthly_sales AS
WITH months AS (
    SELECT DISTINCT month FROM core.calendar
), sales AS (
    SELECT purchase_month,
           count(DISTINCT order_id) AS orders,
           sum(price)               AS revenue
    FROM mart.delivered_items
    GROUP BY purchase_month
)
SELECT m.month,
       coalesce(s.orders, 0)  AS orders,
       coalesce(s.revenue, 0) AS revenue
FROM months m
LEFT JOIN sales s ON s.purchase_month = m.month;

-- Один продавец с продажами = одна строка.
-- Выручка — только по позициям этого продавца, а не по сумме заказа:
-- в одном заказе бывают товары разных продавцов.
CREATE VIEW mart.seller_sales AS
SELECT d.seller_id,
       s.city,
       s.state,
       count(DISTINCT d.order_id) AS orders,
       count(*)                   AS units,
       sum(d.price)               AS revenue
FROM mart.delivered_items d
JOIN core.sellers s USING (seller_id)
GROUP BY d.seller_id, s.city, s.state;

-- Одна категория с продажами = одна строка, с долей в общей выручке.
-- Товары без категории попадают в '__unknown__', поэтому сумма по категориям
-- совпадает с общей выручкой.
CREATE VIEW mart.category_sales AS
WITH totals AS (
    SELECT category_key, sum(price) AS revenue
    FROM mart.delivered_items
    GROUP BY category_key
)
SELECT c.category_key,
       c.name,
       c.name_pt,
       c.is_unknown,
       t.revenue,
       -- При нулевом обороте доля не определена; категория сохраняется, доля — NULL.
       100 * t.revenue / nullif(sum(t.revenue) OVER (), 0) AS revenue_pct
FROM totals t
JOIN core.categories c USING (category_key);

-- Один покупатель-человек = одна строка: сколько заказов, когда первый и
-- последний, сколько принёс выручки. Основа для вопросов про удержание.
-- orders считает заказы всех статусов: «вернулся» — это поведение покупателя.
CREATE VIEW mart.customers AS
SELECT c.customer_unique_id,
       count(o.order_id)                              AS orders,
       count(o.order_id) FILTER (WHERE o.is_delivered) AS delivered_orders,
       min(o.purchased_at)                            AS first_order_at,
       max(o.purchased_at)                            AS last_order_at,
       sum(o.goods_amount) FILTER (WHERE o.is_delivered) AS revenue
FROM core.customers c
LEFT JOIN mart.order_totals o USING (customer_unique_id)
GROUP BY c.customer_unique_id;

-- Реестр проблем качества данных. Одна строка = одна проблема одной сущности.
-- severity:
--   error   — так быть не должно, сборка остановится (см. 90_checks.sql);
--   warning — несостыковка, которую нужно учитывать в отчётах;
--   info    — особенность данных, а не ошибка.
-- У одного заказа может быть несколько проблем, поэтому число проблемных
-- заказов — это count(DISTINCT entity_id), а не count(*).
-- Список соответствует docs/data_issues.md.
CREATE VIEW mart.quality_issues AS
SELECT CASE WHEN is_delivered THEN 'error' ELSE 'info' END AS severity,
       'order_without_items' AS issue_code, 'order' AS entity_type, order_id AS entity_id,
       'статус ' || status_code AS details
FROM mart.order_totals WHERE units = 0
UNION ALL
SELECT 'warning', 'order_without_payment', 'order', order_id, 'статус ' || status_code
FROM mart.order_totals WHERE payment_records = 0
UNION ALL
SELECT 'warning', 'payment_amount_mismatch', 'order', order_id,
       format('платежи минус чек: %s', payment_delta)
FROM mart.order_totals WHERE abs(payment_delta) > 0.01
UNION ALL
SELECT 'warning', 'delivered_without_delivery_date', 'order', order_id, NULL
FROM mart.order_totals WHERE is_delivered AND delivered_customer_at IS NULL
UNION ALL
SELECT 'warning', 'delivery_date_without_delivered_status', 'order', order_id, 'статус ' || status_code
FROM mart.order_totals WHERE NOT is_delivered AND delivered_customer_at IS NOT NULL
UNION ALL
SELECT 'warning', 'carrier_before_approval', 'order', order_id, NULL
FROM core.orders WHERE delivered_carrier_at < approved_at
UNION ALL
SELECT 'warning', 'delivery_before_carrier', 'order', order_id, NULL
FROM core.orders WHERE delivered_customer_at < delivered_carrier_at
UNION ALL
SELECT 'warning', 'delivery_before_purchase', 'order', order_id, NULL
FROM core.orders WHERE delivered_customer_at < purchased_at
UNION ALL
SELECT 'warning', 'missing_category', 'product', product_id, NULL
FROM core.products WHERE category_key = '__unknown__'
UNION ALL
SELECT 'warning', 'missing_category_translation', 'category', category_key, 'показываем португальское название'
FROM core.categories WHERE NOT is_unknown AND name_en IS NULL
UNION ALL
SELECT 'warning', 'zero_installments', 'payment', order_id || ':' || payment_sequential, payment_type
FROM core.order_payments WHERE installments = 0
UNION ALL
SELECT 'warning', 'undefined_payment_type', 'payment', order_id || ':' || payment_sequential, payment_value::text
FROM core.order_payments WHERE payment_type = 'not_defined'
UNION ALL
SELECT 'info', 'multiple_reviews', 'order', order_id, 'отзывов: ' || review_count
FROM mart.order_totals WHERE review_count > 1;
