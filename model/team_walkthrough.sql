-- Знакомство с моделью в DBeaver: выполнять блоки по очереди (Ctrl+Enter).
-- Только SELECT, изменения данных отсутствуют.

-- 1. Убедиться, что открыта нужная база.
SELECT current_database() AS database_name, current_user AS username;

-- 2. Три уровня: одинаковые заказы, разные роли таблиц.
SELECT 'raw.orders: исходник' AS object, count(*) AS rows FROM raw.orders
UNION ALL SELECT 'core.orders: типизированная модель', count(*) FROM core.orders
UNION ALL SELECT 'mart.order_totals: удобный итог', count(*) FROM mart.order_totals;

-- 3. Начать с витрины: одна строка = один заказ.
SELECT order_id, status_code, purchased_at, units, logical_lines,
       goods_amount, freight_amount, order_amount, paid_amount
FROM mart.order_totals ORDER BY purchased_at, order_id LIMIT 10;

-- 4. Один реальный заказ целиком. Позиции и платежи вложены раздельно:
-- не создаём все сочетания их строк.
WITH sample AS (
    SELECT order_id FROM mart.order_totals
    WHERE units > 1 AND payment_records > 1 ORDER BY order_id LIMIT 1
)
SELECT o.order_id, o.goods_amount, o.freight_amount, o.order_amount, o.paid_amount,
       (SELECT jsonb_agg(jsonb_build_object('position',i.order_item_id,'product',i.product_id,
                  'seller',i.seller_id,'price',i.price,'freight',i.freight_value) ORDER BY i.order_item_id)
        FROM core.order_items i WHERE i.order_id=o.order_id) AS items,
       (SELECT jsonb_agg(jsonb_build_object('payment',p.payment_sequential,
                  'type',p.payment_type,'amount',p.payment_value) ORDER BY p.payment_sequential)
        FROM core.order_payments p WHERE p.order_id=o.order_id) AS payments
FROM mart.order_totals o JOIN sample USING(order_id);

-- 5. Демонстрация ошибки: на одном и том же заказе неправильный JOIN
-- повторяет каждую позицию столько раз, сколько у заказа платежей.
WITH sample AS (
    SELECT order_id FROM mart.order_totals
    WHERE units > 1 AND payment_records > 1 ORDER BY order_id LIMIT 1
), wrong AS (
    SELECT i.order_id, count(*) AS joined_rows, sum(i.price) AS inflated_goods_amount
    FROM core.order_items i JOIN core.order_payments p USING(order_id)
    JOIN sample USING(order_id) GROUP BY i.order_id
)
SELECT o.order_id, o.units AS real_units, o.payment_records, w.joined_rows,
       o.goods_amount AS correct_goods_amount, w.inflated_goods_amount AS wrong_goods_amount
FROM mart.order_totals o JOIN wrong w USING(order_id);

-- 6. Один человек может иметь несколько записей и разных адресов.
WITH returning_customer AS (
    SELECT customer_unique_id FROM core.customer_order_profiles
    GROUP BY customer_unique_id HAVING count(*)>1 ORDER BY customer_unique_id LIMIT 1
)
SELECT p.customer_unique_id, p.customer_id, p.city, p.state, o.order_id, o.status_code
FROM core.customer_order_profiles p JOIN returning_customer USING(customer_unique_id)
JOIN core.orders o USING(customer_id) ORDER BY o.purchased_at, o.order_id;

-- 7. NULL-категория и отсутствие перевода — разные ситуации.
-- Исторически выданные категории без текущих товаров тоже могут оставаться.
SELECT c.category_id, c.name_pt, c.name_en, count(p.product_id) AS current_products
FROM core.categories c LEFT JOIN core.products p USING(category_id)
GROUP BY c.category_id, c.name_pt, c.name_en
ORDER BY c.name_pt NULLS FIRST;

-- 8. Диагностика даёт идентификатор для расследования.
SELECT issue_code, count(*) AS records FROM mart.quality_issues GROUP BY 1 ORDER BY 1;
SELECT order_id, details FROM mart.quality_issues
WHERE issue_code='payment_amount_mismatch' ORDER BY order_id LIMIT 10;

-- 9. Связи основной модели: кто на кого ссылается.
SELECT conrelid::regclass AS child_table, confrelid::regclass AS parent_table,
       pg_get_constraintdef(oid) AS rule
FROM pg_constraint WHERE contype='f' AND connamespace='core'::regnamespace
ORDER BY conrelid::regclass::text, conname;

-- 10. Русские описания видны и без навигации по свойствам DBeaver.
SELECT c.relname AS object_name, a.attname AS column_name,
       col_description(c.oid,a.attnum) AS explanation
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
WHERE n.nspname='core' AND c.relkind='r' ORDER BY c.relname,a.attnum;

-- 11. Несколько одинаковых единиц могут составлять одну логическую строку.
-- raw/core остаются на уровне единицы; здесь показан восстановленный уровень.
SELECT order_id, units, logical_lines, goods_amount, order_amount
FROM mart.order_totals WHERE units > logical_lines ORDER BY order_id LIMIT 10;
