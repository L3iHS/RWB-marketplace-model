-- Наполнение core из raw.
--
-- Пустые значения загрузчик кладёт в raw как NULL, поэтому типы приводим
-- напрямую (::timestamp, ::numeric). Если в новой выгрузке встретится мусор,
-- приведение упадёт с ошибкой, и вся сборка откатится. Это сознательно:
-- лучше остановиться, чем молча потерять или исказить строку.
--
-- Порядок загрузки — от справочников к фактам, чтобы внешние ключи
-- всегда ссылались на уже загруженные строки.

-- При первичной сборке эти таблицы пусты; ingest заполняет их прежним
-- опубликованным состоянием в той же транзакции до замены core.
CREATE TEMP TABLE IF NOT EXISTS prior_categories (
    category_key text, name_pt text, name_en text
) ON COMMIT DROP;
CREATE TEMP TABLE IF NOT EXISTS prior_product_categories (
    product_id text, version_no integer, category_key text,
    observed_from timestamptz, observed_to timestamptz
) ON COMMIT DROP;
CREATE TEMP TABLE IF NOT EXISTS prior_item_categories (
    order_id text, order_item_id integer, product_id text, category_version_no integer
) ON COMMIT DROP;
CREATE TEMP TABLE IF NOT EXISTS prior_order_addresses (
    order_id text, zip_code_prefix text, city text, state text, observed_at timestamptz
) ON COMMIT DROP;

-- 1. Люди. DISTINCT здесь создаёт сущность «человек» из адресных записей,
-- а не прячет дубли.
INSERT INTO core.customers (customer_unique_id)
SELECT DISTINCT customer_unique_id
FROM raw.customers;

-- 2. Адресные записи: все исходные customer_id без изменений.
INSERT INTO core.customer_order_profiles (customer_id, customer_unique_id, zip_code_prefix, city, state)
SELECT customer_id, customer_unique_id, customer_zip_code_prefix, customer_city, customer_state
FROM raw.customers;

-- 3. Статусы. Доставленным считается только 'delivered'.
-- Если в данных появится новый статус, он попадёт сюда с is_delivered = false
-- и не превратится в выручку сам по себе.
INSERT INTO core.order_statuses (status_code, is_delivered)
SELECT DISTINCT order_status, order_status = 'delivered'
FROM raw.orders;

-- 4. Категории. Сначала явная строка для товаров без категории.
-- Если в источнике когда-нибудь появится настоящая категория '__unknown__',
-- первичный ключ не даст вставить её второй раз, и сборка остановится.
INSERT INTO core.categories (category_key, name_pt, name_en)
VALUES ('__unknown__', NULL, NULL);

-- Затем все названия из товаров и из справочника перевода.
-- UNION убирает повторы. Перевод присоединяем через LEFT JOIN:
-- категория без перевода остаётся, у неё просто пустой name_en.
INSERT INTO core.categories (category_key, name_pt, name_en)
SELECT n.name_pt, n.name_pt, coalesce(t.product_category_name_english, h.name_en)
FROM (
    SELECT product_category_name AS name_pt FROM raw.products
    WHERE product_category_name IS NOT NULL
    UNION
    SELECT product_category_name FROM raw.product_category_translation
    UNION
    SELECT name_pt FROM prior_categories WHERE name_pt IS NOT NULL
) n
LEFT JOIN raw.product_category_translation t ON t.product_category_name = n.name_pt
LEFT JOIN prior_categories h ON h.name_pt = n.name_pt;

-- 5. Товары. Товар без категории ссылается на '__unknown__', а не теряется:
-- иначе сумма выручки по категориям не сойдётся с общей.
INSERT INTO core.products (product_id, category_key, name_length, description_length,
                           photos_qty, weight_g, length_cm, height_cm, width_cm)
SELECT p.product_id,
       coalesce(p.product_category_name, '__unknown__'),
       p.product_name_lenght::integer,  -- опечатка lenght — из исходного файла
       p.product_description_lenght::integer,
       p.product_photos_qty::integer,
       p.product_weight_g::integer,
       p.product_length_cm::integer,
       p.product_height_cm::integer,
       p.product_width_cm::integer
FROM raw.products p;

INSERT INTO core.product_category_history
SELECT * FROM prior_product_categories;

-- Закрываем только изменившуюся текущую версию, предыдущие не переписываем.
UPDATE core.product_category_history h
SET observed_to = p._loaded_at
FROM raw.products p
WHERE h.product_id = p.product_id AND h.observed_to IS NULL
  AND h.category_key <> coalesce(p.product_category_name, '__unknown__');

INSERT INTO core.product_category_history
    (product_id, version_no, category_key, observed_from)
SELECT p.product_id,
       coalesce((SELECT max(h.version_no) FROM core.product_category_history h
                 WHERE h.product_id = p.product_id), 0) + 1,
       p.category_key, r._loaded_at
FROM core.products p JOIN raw.products r USING (product_id)
WHERE NOT EXISTS (SELECT 1 FROM core.product_category_history h
                  WHERE h.product_id = p.product_id AND h.observed_to IS NULL);

-- 6. Продавцы.
INSERT INTO core.sellers (seller_id, zip_code_prefix, city, state)
SELECT seller_id, seller_zip_code_prefix, seller_city, seller_state
FROM raw.sellers;

-- 7. Заказы всех статусов.
INSERT INTO core.orders (order_id, customer_id, status_code, purchased_at, approved_at,
                         delivered_carrier_at, delivered_customer_at, estimated_delivery_at,
                         source_file, loaded_at)
SELECT order_id, customer_id, order_status,
       order_purchase_timestamp::timestamp,
       order_approved_at::timestamp,
       order_delivered_carrier_date::timestamp,
       order_delivered_customer_date::timestamp,
       order_estimated_delivery_date::timestamp,
       _source_file, _loaded_at
FROM raw.orders;

INSERT INTO core.order_addresses (order_id, zip_code_prefix, city, state, observed_at)
SELECT o.order_id,
       CASE WHEN a.order_id IS NOT NULL THEN a.zip_code_prefix ELSE p.zip_code_prefix END,
       CASE WHEN a.order_id IS NOT NULL THEN a.city ELSE p.city END,
       CASE WHEN a.order_id IS NOT NULL THEN a.state ELSE p.state END,
       CASE WHEN a.order_id IS NOT NULL THEN a.observed_at ELSE o.loaded_at END
FROM core.orders o JOIN core.customer_order_profiles p USING (customer_id)
LEFT JOIN prior_order_addresses a USING (order_id);

-- 8. Позиции: каждая исходная строка как есть, одинаковые единицы не схлопываем.
INSERT INTO core.order_items (order_id, order_item_id, product_id, category_version_no, seller_id,
                              shipping_limit_at, price, freight_value, source_file, loaded_at)
SELECT r.order_id, r.order_item_id::integer, r.product_id,
       coalesce(old.category_version_no, h.version_no), r.seller_id,
       r.shipping_limit_date::timestamp, r.price::numeric, r.freight_value::numeric,
       r._source_file, r._loaded_at
FROM raw.order_items r
JOIN core.product_category_history h ON h.product_id = r.product_id AND h.observed_to IS NULL
LEFT JOIN prior_item_categories old ON old.order_id = r.order_id
    AND old.order_item_id = r.order_item_id::integer AND old.product_id = r.product_id;

-- 9. Платежи. С позициями при загрузке не соединяем: у них разный уровень.
INSERT INTO core.order_payments (order_id, payment_sequential, payment_type,
                                 installments, payment_value, source_file, loaded_at)
SELECT order_id, payment_sequential::integer, payment_type,
       payment_installments::integer, payment_value::numeric,
       _source_file, _loaded_at
FROM raw.order_payments;

-- 10. Отзывы.
INSERT INTO core.order_reviews (review_id, order_id, score, comment_title, comment_message,
                                created_at, answered_at, source_file, loaded_at)
SELECT review_id, order_id, review_score::integer, review_comment_title, review_comment_message,
       review_creation_date::timestamp, review_answer_timestamp::timestamp,
       _source_file, _loaded_at
FROM raw.order_reviews;

-- 11. Календарь: от первого месяца с заказами до конца месяца самой поздней
-- даты в заказах (обещанная доставка бывает позже последней покупки).
INSERT INTO core.calendar (date, month, year, month_num, day_of_week, is_weekend)
SELECT d::date,
       date_trunc('month', d)::date,
       extract(year FROM d)::integer,
       extract(month FROM d)::integer,
       extract(isodow FROM d)::integer,
       extract(isodow FROM d) IN (6, 7)
FROM generate_series(
    (SELECT date_trunc('month', min(purchased_at)) FROM core.orders),
    (SELECT date_trunc('month', max(greatest(purchased_at, delivered_customer_at, estimated_delivery_at)))
            + interval '1 month - 1 day'
     FROM core.orders),
    interval '1 day'
) AS d;

-- Статистика для планировщика запросов после массовой загрузки.
ANALYZE core.customers, core.customer_order_profiles, core.order_statuses,
        core.categories, core.products, core.sellers, core.orders,
        core.order_items, core.order_payments, core.order_reviews, core.calendar,
        core.product_category_history, core.order_addresses;
