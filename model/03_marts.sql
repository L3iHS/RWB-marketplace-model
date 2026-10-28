-- Витрины mart: готовые наборы для отчётов поверх core.
-- Это представления (view): они не хранят данные, а пересчитываются из core
-- при каждом запросе, поэтому не могут разойтись с моделью.

-- Один заказ = одна строка, с итогами по позициям и платежам.
--
-- Главное правило: позиции и платежи сначала сворачиваем до уровня заказа
-- каждый отдельно, и только потом присоединяем к заказу. Если соединить
-- позиции и платежи напрямую, суммы размножатся: заказ с двумя товарами
-- (100 и 50) и двумя платежами (120 и 30) даст 4 строки, и товары
-- посчитаются как 300 вместо 150.
--
-- LEFT JOIN сохраняет заказы без позиций и без платежей. Для них суммы
-- остаются NULL, а не 0: отсутствие данных не доказывает нулевую сумму.
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
)
SELECT o.order_id,
       p.customer_unique_id,
       o.customer_id,
       o.status_code,
       s.is_delivered,
       o.purchased_at,
       date_trunc('month', o.purchased_at)::date AS purchase_month,
       o.approved_at,
       o.delivered_carrier_at,
       o.delivered_customer_at,
       o.estimated_delivery_at,
       -- Срок доставки и опоздание считаем только когда известны обе даты.
       o.delivered_customer_at::date - o.purchased_at::date AS delivery_days,
       o.delivered_customer_at::date > o.estimated_delivery_at::date AS is_late,
       i.units,
       i.lines,
       i.sellers,
       i.goods_amount,
       i.freight_amount,
       i.order_amount,
       pay.payment_records,
       pay.paid_amount
FROM core.orders o
JOIN core.order_statuses s USING (status_code)
JOIN core.customer_order_profiles p USING (customer_id)
LEFT JOIN items i USING (order_id)
LEFT JOIN payments pay USING (order_id);

-- Одна строка = одна единица товара доставленного заказа.
-- Здесь применяется правило выручки: выручка = сумма price этих строк.
-- Уровень позиции позволяет делить выручку по продавцам и категориям
-- без распределения суммы заказа: у каждой позиции свой продавец и товар.
CREATE VIEW mart.delivered_items AS
SELECT i.order_id,
       i.order_item_id,
       i.product_id,
       i.seller_id,
       pr.category_id,
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

-- Реестр проблем качества данных. Одна строка = одна проблема одной сущности.
-- У одного заказа может быть несколько проблем, поэтому число проблемных
-- заказов — это count(DISTINCT order_id), а не count(*).
-- Список соответствует docs/data_issues.md.
CREATE VIEW mart.quality_issues AS
SELECT 'order_without_items' AS issue_code, 'order' AS entity_type, order_id AS entity_id,
       status_code AS details
FROM mart.order_totals WHERE units IS NULL
UNION ALL
SELECT 'order_without_payment', 'order', order_id, status_code
FROM mart.order_totals WHERE payment_records IS NULL
UNION ALL
SELECT 'payment_amount_mismatch', 'order', order_id,
       format('позиции %s, платежи %s', order_amount, paid_amount)
FROM mart.order_totals WHERE abs(order_amount - paid_amount) > 0.01
UNION ALL
SELECT 'delivered_without_delivery_date', 'order', order_id, NULL
FROM mart.order_totals WHERE is_delivered AND delivered_customer_at IS NULL
UNION ALL
SELECT 'delivery_date_without_delivered_status', 'order', order_id, status_code
FROM mart.order_totals WHERE NOT is_delivered AND delivered_customer_at IS NOT NULL
UNION ALL
SELECT 'carrier_before_approval', 'order', order_id, NULL
FROM core.orders WHERE delivered_carrier_at < approved_at
UNION ALL
SELECT 'delivery_before_carrier', 'order', order_id, NULL
FROM core.orders WHERE delivered_customer_at < delivered_carrier_at
UNION ALL
SELECT 'missing_category', 'product', p.product_id, NULL
FROM core.products p JOIN core.categories c USING (category_id)
WHERE c.name_pt IS NULL
UNION ALL
SELECT 'missing_category_translation', 'product', p.product_id, c.name_pt
FROM core.products p JOIN core.categories c USING (category_id)
WHERE c.name_pt IS NOT NULL AND c.name_en IS NULL
UNION ALL
SELECT 'zero_installments', 'payment', order_id || ':' || payment_sequential, payment_type
FROM core.order_payments WHERE installments = 0
UNION ALL
SELECT 'undefined_payment_type', 'payment', order_id || ':' || payment_sequential, payment_value::text
FROM core.order_payments WHERE payment_type = 'not_defined';
