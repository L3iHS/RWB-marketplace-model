-- Категории сохраняют выданные ID, в том числе при временном исчезновении.
-- Остальные таблицы — полное обновление. Без CASCADE; внешние зависимости
-- не удаляются и не очищаются автоматически.
TRUNCATE core.order_reviews, core.order_payments, core.order_items,
         core.orders, core.products, core.sellers,
         core.customer_order_profiles, core.customers,
         core.order_statuses, core.payment_types;

-- 1. Выделяем людей из исходных адресных записей.
-- DISTINCT здесь создаёт сущность человека, а не скрывает дубли фактов.
INSERT INTO core.customers (customer_unique_id)
SELECT DISTINCT customer_unique_id FROM raw.customers;

-- 2. Сохраняем все исходные customer_id и их географию.
-- Один человек может иметь несколько адресных записей.
INSERT INTO core.customer_order_profiles (customer_id, customer_unique_id, zip_code_prefix, city, state)
SELECT customer_id, customer_unique_id, customer_zip_code_prefix, customer_city, customer_state FROM raw.customers;

-- 3. Справочники получают все значения источника.
-- Новое значение статуса не должно автоматически превращаться в продажу.
INSERT INTO core.order_statuses (status_code, is_delivered)
SELECT DISTINCT order_status, order_status='delivered' FROM raw.orders;

INSERT INTO core.payment_types (payment_type)
SELECT DISTINCT payment_type FROM raw.order_payments;

-- 4. Категории: UNION собирает множество названий из двух источников.
-- IS NOT DISTINCT FROM — равенство, при котором NULL совпадает с NULL.
-- Обычное сравнение NULL = NULL не даёт true и потеряло бы товары без категории.
-- NULL всегда обозначает отсутствие категории. Пустое имя товара = NULL.
-- Сначала обновляем переводы существующих категорий, затем добавляем новые.
-- Не используем nextval для уже известных категорий.
WITH names AS (
    SELECT NULL::text AS name_pt
    UNION SELECT nullif(product_category_name,'') FROM raw.products
    UNION SELECT product_category_name FROM raw.product_category_translation
), source AS (
    SELECT n.name_pt, nullif(t.product_category_name_english,'') AS name_en
    FROM names n LEFT JOIN raw.product_category_translation t ON t.product_category_name=n.name_pt
)
UPDATE core.categories c SET name_en=s.name_en
FROM source s WHERE c.name_pt IS NOT DISTINCT FROM s.name_pt;

WITH names AS (
    SELECT NULL::text AS name_pt
    UNION SELECT nullif(product_category_name,'') FROM raw.products
    UNION SELECT product_category_name FROM raw.product_category_translation
)
INSERT INTO core.categories (name_pt, name_en)
SELECT n.name_pt, nullif(t.product_category_name_english,'')
FROM names n LEFT JOIN raw.product_category_translation t ON t.product_category_name=n.name_pt
WHERE NOT EXISTS (SELECT 1 FROM core.categories c WHERE c.name_pt IS NOT DISTINCT FROM n.name_pt)
ORDER BY n.name_pt NULLS FIRST;

-- 5. Карточки товаров. Имена целевых колонок перечислены явно:
-- слева — что заполняем; SELECT справа — из каких полей и преобразований.
-- NULLIF(BTRIM(x), '') превращает пустое значение в NULL до приведения типа.
-- Правильная категория уже существует к моменту загрузки товара.
INSERT INTO core.products (product_id, category_id, name_length, description_length,
    photos_qty, weight_g, length_cm, height_cm, width_cm)
SELECT p.product_id, c.category_id,
    nullif(btrim(p.product_name_lenght),'')::integer,
    nullif(btrim(p.product_description_lenght),'')::integer,
    nullif(btrim(p.product_photos_qty),'')::integer,
    nullif(btrim(p.product_weight_g),'')::integer,
    nullif(btrim(p.product_length_cm),'')::integer,
    nullif(btrim(p.product_height_cm),'')::integer,
    nullif(btrim(p.product_width_cm),'')::integer
FROM raw.products p JOIN core.categories c ON c.name_pt IS NOT DISTINCT FROM nullif(p.product_category_name,'');

INSERT INTO core.sellers (seller_id, zip_code_prefix, city, state)
SELECT seller_id, seller_zip_code_prefix, seller_city, seller_state FROM raw.sellers;

-- 6. Заказы всех статусов. Фильтра delivered здесь нет: иначе потеряем
-- отмены, незавершённые оформления и возможность считать новые показатели.
-- Timestamp без часового пояса отражает точность исходника.
INSERT INTO core.orders (order_id, customer_id, status_code, purchased_at,
    approved_at, delivered_carrier_at, delivered_customer_at, estimated_delivery_at,
    source_file, source_loaded_at)
SELECT order_id, customer_id, order_status, order_purchase_timestamp::timestamp,
    nullif(btrim(order_approved_at),'')::timestamp,
    nullif(btrim(order_delivered_carrier_date),'')::timestamp,
    nullif(btrim(order_delivered_customer_date),'')::timestamp,
    nullif(btrim(order_estimated_delivery_date),'')::timestamp, _source_file, _loaded_at FROM raw.orders;

-- 7. Подробные факты. Каждая исходная строка сохраняется как отдельная
-- запись на своём уровне. Позиции не соединяем с платежами при переносе.
-- Денежный numeric сохраняет точность, исходный файл помогает расследованию.
INSERT INTO core.order_items (order_id, order_item_id, product_id, seller_id,
    shipping_limit_at, price, freight_value, source_file, source_loaded_at)
SELECT order_id, order_item_id::integer, product_id, seller_id,
    nullif(btrim(shipping_limit_date),'')::timestamp, price::numeric, freight_value::numeric,
    _source_file, _loaded_at FROM raw.order_items;

-- Платёжная запись не равна части рассрочки: payment_value не умножаем.
INSERT INTO core.order_payments (order_id, payment_sequential, payment_type,
    installments, payment_value, source_file, source_loaded_at)
SELECT order_id, payment_sequential::integer, payment_type, payment_installments::integer,
    payment_value::numeric, _source_file, _loaded_at FROM raw.order_payments;

-- review_id повторяется у разных заказов; уникальность пары защищает PK.
INSERT INTO core.order_reviews (review_id, order_id, score, comment_title,
    comment_message, created_at, answered_at, source_file, source_loaded_at)
SELECT review_id, order_id, review_score::integer, review_comment_title, review_comment_message,
    nullif(btrim(review_creation_date),'')::timestamp,
    nullif(btrim(review_answer_timestamp),'')::timestamp, _source_file, _loaded_at FROM raw.order_reviews;
