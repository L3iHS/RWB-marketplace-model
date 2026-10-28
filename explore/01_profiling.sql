-- Разведка сырых данных перед проектированием модели.
-- Каждый блок отвечает на один вопрос к данным. Выводы — в docs/findings.md.
-- Запуск целиком: bash build.sh explore/01_profiling.sql
-- или по одному запросу в pgAdmin (Query Tool).

\pset footer off

-- 1. Сколько строк в каждой таблице ---------------------------------------
\echo '\n=== 1. Число строк'
SELECT 'orders' AS tbl, count(*) FROM raw.orders
UNION ALL SELECT 'order_items',    count(*) FROM raw.order_items
UNION ALL SELECT 'order_payments', count(*) FROM raw.order_payments
UNION ALL SELECT 'order_reviews',  count(*) FROM raw.order_reviews
UNION ALL SELECT 'products',       count(*) FROM raw.products
UNION ALL SELECT 'sellers',        count(*) FROM raw.sellers
UNION ALL SELECT 'customers',      count(*) FROM raw.customers
UNION ALL SELECT 'category_translation', count(*) FROM raw.product_category_translation;

-- 2. Какие колонки однозначно определяют строку (кандидаты в ключи) -------
-- Если rows = distinct_key, колонка (или набор колонок) — ключ таблицы.
\echo '\n=== 2. Уникальность ключей'
SELECT 'orders(order_id)' AS key_candidate, count(*) AS rows,
       count(DISTINCT order_id) AS distinct_key FROM raw.orders
UNION ALL
SELECT 'order_items(order_id, order_item_id)', count(*),
       count(DISTINCT (order_id, order_item_id)) FROM raw.order_items
UNION ALL
SELECT 'order_payments(order_id, payment_sequential)', count(*),
       count(DISTINCT (order_id, payment_sequential)) FROM raw.order_payments
UNION ALL
SELECT 'order_reviews(review_id)', count(*),
       count(DISTINCT review_id) FROM raw.order_reviews
UNION ALL
SELECT 'order_reviews(order_id)', count(*),
       count(DISTINCT order_id) FROM raw.order_reviews
UNION ALL
SELECT 'order_reviews(review_id, order_id)', count(*),
       count(DISTINCT (review_id, order_id)) FROM raw.order_reviews
UNION ALL
SELECT 'products(product_id)', count(*),
       count(DISTINCT product_id) FROM raw.products
UNION ALL
SELECT 'sellers(seller_id)', count(*),
       count(DISTINCT seller_id) FROM raw.sellers
UNION ALL
SELECT 'customers(customer_id)', count(*),
       count(DISTINCT customer_id) FROM raw.customers
UNION ALL
SELECT 'customers(customer_unique_id)', count(*),
       count(DISTINCT customer_unique_id) FROM raw.customers
UNION ALL
SELECT 'category_translation(name)', count(*),
       count(DISTINCT product_category_name) FROM raw.product_category_translation;

-- 3. Статусы заказов -------------------------------------------------------
\echo '\n=== 3. Статусы заказов'
SELECT order_status, count(*) AS orders,
       round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct
FROM raw.orders
GROUP BY 1 ORDER BY 2 DESC;

-- 4. Пропуски в датах заказа в разрезе статусов ---------------------------
-- Помогает понять, какие пропуски «нормальные» (заказ ещё не доставлен),
-- а какие подозрительные (доставлен, но даты вручения нет).
\echo '\n=== 4. Пропуски дат по статусам'
SELECT order_status,
       count(*) AS orders,
       count(*) FILTER (WHERE order_approved_at IS NULL)             AS no_approved,
       count(*) FILTER (WHERE order_delivered_carrier_date IS NULL)  AS no_carrier,
       count(*) FILTER (WHERE order_delivered_customer_date IS NULL) AS no_delivered
FROM raw.orders
GROUP BY 1 ORDER BY 2 DESC;

-- 5. Покупатели: customer_id против customer_unique_id ---------------------
-- Если на один unique_id приходится несколько customer_id,
-- значит customer_id выдаётся на заказ, а не на человека.
\echo '\n=== 5. Сколько customer_id у одного customer_unique_id'
SELECT ids_per_person, count(*) AS persons
FROM (
    SELECT customer_unique_id, count(*) AS ids_per_person
    FROM raw.customers GROUP BY 1
) t
GROUP BY 1 ORDER BY 1;

\echo '\n=== 5b. Сколько заказов на один customer_id'
SELECT orders_per_customer_id, count(*) AS customer_ids
FROM (
    SELECT customer_id, count(*) AS orders_per_customer_id
    FROM raw.orders GROUP BY 1
) t
GROUP BY 1 ORDER BY 1;

-- 6. Связи: есть ли «сироты» (ссылки в никуда) ----------------------------
\echo '\n=== 6. Ссылочная целостность'
SELECT 'order_items -> orders' AS link, count(*) AS orphans
FROM raw.order_items i
WHERE NOT EXISTS (SELECT 1 FROM raw.orders o WHERE o.order_id = i.order_id)
UNION ALL
SELECT 'order_items -> products', count(*)
FROM raw.order_items i
WHERE NOT EXISTS (SELECT 1 FROM raw.products p WHERE p.product_id = i.product_id)
UNION ALL
SELECT 'order_items -> sellers', count(*)
FROM raw.order_items i
WHERE NOT EXISTS (SELECT 1 FROM raw.sellers s WHERE s.seller_id = i.seller_id)
UNION ALL
SELECT 'orders -> customers', count(*)
FROM raw.orders o
WHERE NOT EXISTS (SELECT 1 FROM raw.customers c WHERE c.customer_id = o.customer_id)
UNION ALL
SELECT 'order_payments -> orders', count(*)
FROM raw.order_payments p
WHERE NOT EXISTS (SELECT 1 FROM raw.orders o WHERE o.order_id = p.order_id)
UNION ALL
SELECT 'order_reviews -> orders', count(*)
FROM raw.order_reviews r
WHERE NOT EXISTS (SELECT 1 FROM raw.orders o WHERE o.order_id = r.order_id)
UNION ALL
SELECT 'products -> category_translation (category not null)', count(*)
FROM raw.products p
WHERE p.product_category_name IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM raw.product_category_translation t
                  WHERE t.product_category_name = p.product_category_name);

-- 7. Обратная сторона: заказы без позиций, платежей, отзывов --------------
\echo '\n=== 7. Заказы без позиций / платежей / отзывов (по статусам)'
SELECT o.order_status,
       count(*) AS orders,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM raw.order_items i
                                          WHERE i.order_id = o.order_id))    AS no_items,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM raw.order_payments p
                                          WHERE p.order_id = o.order_id))    AS no_payments,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM raw.order_reviews r
                                          WHERE r.order_id = o.order_id))    AS no_reviews
FROM raw.orders o
GROUP BY 1 ORDER BY 2 DESC;

-- 8. Уровень order_items: строка = единица товара? -------------------------
-- order_item_id — порядковый номер внутри заказа. Смотрим, повторяется ли
-- один и тот же товар в заказе несколькими строками.
\echo '\n=== 8. Позиции в заказе'
SELECT count(*)                                   AS item_rows,
       count(DISTINCT order_id)                   AS orders_with_items,
       count(DISTINCT (order_id, product_id, seller_id)) AS distinct_lines,
       max(order_item_id::int)                    AS max_item_number
FROM raw.order_items;

\echo '\n=== 8b. Пример заказа с повтором одного товара'
SELECT i.order_id, i.order_item_id, i.product_id, i.seller_id, i.price, i.freight_value
FROM raw.order_items i
WHERE i.order_id = (
    SELECT order_id FROM raw.order_items
    GROUP BY order_id, product_id HAVING count(*) > 2 LIMIT 1
)
ORDER BY i.order_item_id::int;

\echo '\n=== 8c. Сколько продавцов в одном заказе'
SELECT sellers_in_order, count(*) AS orders
FROM (SELECT order_id, count(DISTINCT seller_id) AS sellers_in_order
      FROM raw.order_items GROUP BY 1) t
GROUP BY 1 ORDER BY 1;

-- 9. Категории товаров -----------------------------------------------------
\echo '\n=== 9. Категории'
SELECT count(*) FILTER (WHERE product_category_name IS NULL) AS products_without_category,
       count(DISTINCT product_category_name)                 AS categories_in_products,
       (SELECT count(*) FROM raw.product_category_translation) AS categories_in_translation
FROM raw.products;

\echo '\n=== 9b. Категории без перевода'
SELECT p.product_category_name, count(*) AS products
FROM raw.products p
LEFT JOIN raw.product_category_translation t USING (product_category_name)
WHERE p.product_category_name IS NOT NULL AND t.product_category_name IS NULL
GROUP BY 1;

-- 10. Заказы по месяцам: есть ли дыры --------------------------------------
\echo '\n=== 10. Заказы по месяцам (вместе с пустыми)'
SELECT to_char(m, 'YYYY-MM') AS month, count(o.order_id) AS orders
FROM generate_series('2016-09-01'::date, '2018-10-01'::date, interval '1 month') m
LEFT JOIN raw.orders o
       ON date_trunc('month', o.order_purchase_timestamp::timestamp) = m
GROUP BY m ORDER BY m;

-- 11. Сходятся ли деньги: позиции против платежей --------------------------
\echo '\n=== 11. Сумма позиций (price + freight) против суммы платежей'
WITH items AS (
    SELECT order_id, sum(price::numeric + freight_value::numeric) AS items_total
    FROM raw.order_items GROUP BY 1
), pays AS (
    SELECT order_id, sum(payment_value::numeric) AS paid_total
    FROM raw.order_payments GROUP BY 1
)
SELECT count(*)                                                       AS orders_with_both,
       count(*) FILTER (WHERE abs(items_total - paid_total) <= 0.01)  AS match,
       count(*) FILTER (WHERE paid_total - items_total > 0.01)        AS paid_more,
       count(*) FILTER (WHERE items_total - paid_total > 0.01)        AS paid_less,
       sum(items_total)                                               AS items_sum,
       sum(paid_total)                                                AS paid_sum
FROM items JOIN pays USING (order_id);

\echo '\n=== 11b. Типы платежей'
SELECT payment_type, count(*) AS payments, count(DISTINCT order_id) AS orders,
       sum(payment_value::numeric) AS total
FROM raw.order_payments GROUP BY 1 ORDER BY 2 DESC;

-- 12. Странные значения ----------------------------------------------------
\echo '\n=== 12. Подозрительные значения'
SELECT 'items: price <= 0' AS check, count(*) AS rows
FROM raw.order_items WHERE price::numeric <= 0
UNION ALL
SELECT 'items: freight = 0', count(*)
FROM raw.order_items WHERE freight_value::numeric = 0
UNION ALL
SELECT 'payments: value = 0', count(*)
FROM raw.order_payments WHERE payment_value::numeric = 0
UNION ALL
SELECT 'payments: installments = 0', count(*)
FROM raw.order_payments WHERE payment_installments::int = 0
UNION ALL
SELECT 'orders: delivered раньше покупки', count(*)
FROM raw.orders
WHERE order_delivered_customer_date::timestamp < order_purchase_timestamp::timestamp
UNION ALL
SELECT 'orders: передан в доставку раньше подтверждения', count(*)
FROM raw.orders
WHERE order_delivered_carrier_date::timestamp < order_approved_at::timestamp
UNION ALL
SELECT 'orders: delivered, но нет даты вручения', count(*)
FROM raw.orders
WHERE order_status = 'delivered' AND order_delivered_customer_date IS NULL
UNION ALL
SELECT 'orders: не delivered, но есть дата вручения', count(*)
FROM raw.orders
WHERE order_status <> 'delivered' AND order_delivered_customer_date IS NOT NULL
UNION ALL
SELECT 'products: без габаритов/веса', count(*)
FROM raw.products WHERE product_weight_g IS NULL OR product_length_cm IS NULL;

-- 13. Отзывы: дубли ---------------------------------------------------------
\echo '\n=== 13. Отзывы на заказ и заказы на отзыв'
SELECT 'заказов с >1 отзывом' AS what, count(*) AS n
FROM (SELECT order_id FROM raw.order_reviews GROUP BY 1 HAVING count(*) > 1) t
UNION ALL
SELECT 'review_id на >1 заказ', count(*)
FROM (SELECT review_id FROM raw.order_reviews GROUP BY 1 HAVING count(DISTINCT order_id) > 1) t;

-- 14. Продавцы и покупатели: города и штаты --------------------------------
\echo '\n=== 14. Разнобой в написании городов (пример)'
SELECT seller_city, count(*) FROM raw.sellers
WHERE seller_city ILIKE 'sao paulo%' OR seller_city ILIKE 'são paulo%' OR seller_city ILIKE 'sp%'
GROUP BY 1 ORDER BY 2 DESC LIMIT 10;
