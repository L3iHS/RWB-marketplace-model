CREATE SCHEMA IF NOT EXISTS mart;

-- Один итог на заказ; отсутствие позиций/платежей остаётся NULL.
CREATE OR REPLACE VIEW mart.order_totals AS
-- CTE items и payments сначала дают по одной строке на order_id.
-- Затем LEFT JOIN сохраняет даже заказ без позиций или платежа.
-- COALESCE(...,0) не применяем: отсутствие суммы не доказывает нулевую сумму.
WITH items AS (
    SELECT order_id, count(*) AS units,
           count(DISTINCT (product_id, seller_id)) AS analytical_lines,
           -- Аналитическая строка: одинаковый товар/продавец и коммерческие
           -- условия. Повторные единицы такой строки дают её количество.
           count(DISTINCT (product_id, seller_id, price, freight_value, shipping_limit_at)) AS logical_lines,
           sum(price) AS goods_amount, sum(freight_value) AS freight_amount,
           sum(price + freight_value) AS order_amount
    FROM core.order_items GROUP BY order_id
), payments AS (
    SELECT order_id, count(*) AS payment_records, sum(payment_value) AS paid_amount
    FROM core.order_payments GROUP BY order_id
)
SELECT o.*, s.is_delivered, i.units, i.analytical_lines,
       i.goods_amount, i.freight_amount, i.order_amount,
       p.payment_records, p.paid_amount, i.logical_lines
FROM core.orders o JOIN core.order_statuses s USING (status_code)
LEFT JOIN items i USING (order_id) LEFT JOIN payments p USING (order_id);

-- Одна запись = одна исходная единица товара доставленного заказа.
-- Только здесь применяется правило выручки. Индивидуальные единицы
-- позволяют делить оборот по продавцам и категориям без распределения платежей.
CREATE OR REPLACE VIEW mart.delivered_items AS
SELECT i.*, o.purchased_at, o.customer_id, p.category_id
FROM core.order_items i JOIN core.orders o USING (order_id)
JOIN core.order_statuses s USING (status_code)
JOIN core.products p USING (product_id)
WHERE s.is_delivered;

-- Диагностика сохраняет идентификаторы; одна сущность может иметь несколько проблем.
-- UNION ALL объединяет предупреждения, сохраняя каждую причину.
-- Один заказ может встретиться несколько раз: count(*) не равно числу
-- уникальных проблемных заказов. Для их числа нужен count(DISTINCT order_id).
CREATE OR REPLACE VIEW mart.quality_issues AS
SELECT 'order_without_items'::text AS issue_code, 'order'::text AS entity_type,
       order_id AS entity_id, order_id, 'Нет позиций'::text AS details
FROM mart.order_totals WHERE units IS NULL
UNION ALL
SELECT 'order_without_payment', 'order', order_id, order_id, 'Нет платёжной записи'
FROM mart.order_totals WHERE payment_records IS NULL
UNION ALL
SELECT 'order_without_review', 'order', o.order_id, o.order_id, 'Нет отзыва'
FROM core.orders o WHERE NOT EXISTS (SELECT 1 FROM core.order_reviews r WHERE r.order_id=o.order_id)
UNION ALL
SELECT 'payment_amount_mismatch', 'order', order_id, order_id,
       format('positions=%s; payments=%s; difference=%s', order_amount, paid_amount, paid_amount-order_amount)
FROM mart.order_totals WHERE abs(order_amount-paid_amount)>0.01
UNION ALL
SELECT 'delivered_without_delivery_date', 'order', order_id, order_id, 'delivered без даты вручения'
FROM mart.order_totals WHERE is_delivered AND delivered_customer_at IS NULL
UNION ALL
SELECT 'delivered_without_carrier_date', 'order', order_id, order_id, 'delivered без даты передачи перевозчику'
FROM mart.order_totals WHERE is_delivered AND delivered_carrier_at IS NULL
UNION ALL
SELECT 'delivered_without_approval_date', 'order', order_id, order_id, 'delivered без подтверждения оплаты'
FROM mart.order_totals WHERE is_delivered AND approved_at IS NULL
UNION ALL
SELECT 'delivery_before_carrier', 'order', order_id, order_id, 'Вручение раньше передачи перевозчику'
FROM core.orders WHERE delivered_customer_at < delivered_carrier_at
UNION ALL
SELECT 'approval_before_purchase', 'order', order_id, order_id, 'Подтверждение оплаты раньше покупки'
FROM core.orders WHERE approved_at < purchased_at
UNION ALL
SELECT 'missing_category', 'product', p.product_id, NULL::text, 'Категория не указана'
FROM core.products p JOIN core.categories c USING(category_id) WHERE c.name_pt IS NULL
UNION ALL
SELECT 'missing_category_translation', 'product', p.product_id, NULL::text, c.name_pt
FROM core.products p JOIN core.categories c USING(category_id) WHERE c.name_pt IS NOT NULL AND c.name_en IS NULL
UNION ALL
SELECT 'zero_installments', 'payment', order_id || ':' || payment_sequential, order_id, 'Нулевое число частей рассрочки'
FROM core.order_payments WHERE installments=0
UNION ALL
SELECT 'new_order_status', 'order', order_id, order_id, status_code
FROM core.orders WHERE status_code NOT IN ('delivered','shipped','canceled','unavailable','invoiced','processing','created','approved')
UNION ALL
SELECT 'new_payment_type', 'payment', order_id || ':' || payment_sequential, order_id, payment_type
FROM core.order_payments WHERE payment_type NOT IN ('credit_card','boleto','voucher','debit_card','not_defined');
