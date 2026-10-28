-- Типы и обязательные ключи валидируются PostgreSQL. Некорректный вход прерывает всю транзакцию.
-- Пустые необязательные значения становятся NULL, исходные строки остаются в raw.
INSERT INTO core.buyers SELECT DISTINCT nullif(btrim(customer_unique_id),'') FROM raw.customers;
INSERT INTO core.customer_profiles
SELECT nullif(btrim(customer_id),''),nullif(btrim(customer_unique_id),''),nullif(btrim(customer_zip_code_prefix),''),
       nullif(btrim(customer_city),''),nullif(btrim(customer_state),''),_source_file FROM raw.customers;
INSERT INTO core.sellers
SELECT nullif(btrim(seller_id),''),nullif(btrim(seller_zip_code_prefix),''),nullif(btrim(seller_city),''),nullif(btrim(seller_state),''),_source_file FROM raw.sellers;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM raw.products WHERE btrim(product_category_name)='__unknown__') OR
       EXISTS (SELECT 1 FROM raw.product_category_translation WHERE btrim(product_category_name)='__unknown__') THEN
        RAISE EXCEPTION 'Категория __unknown__ зарезервирована; требуется миграция ключа неизвестной категории';
    END IF;
END $$;
INSERT INTO core.categories VALUES ('__unknown__',NULL,NULL,true);
INSERT INTO core.categories(category_key,name_pt,name_en)
SELECT names.name,names.name,nullif(btrim(t.product_category_name_english),'')
FROM (
    SELECT nullif(btrim(product_category_name),'') AS name FROM raw.products
    UNION SELECT nullif(btrim(product_category_name),'') FROM raw.product_category_translation
) names LEFT JOIN raw.product_category_translation t ON nullif(btrim(t.product_category_name),'')=names.name
WHERE names.name IS NOT NULL;
INSERT INTO core.products
SELECT nullif(btrim(product_id),''),coalesce(nullif(btrim(product_category_name),''),'__unknown__'),
       nullif(btrim(product_name_lenght),'')::integer,nullif(btrim(product_description_lenght),'')::integer,
       nullif(btrim(product_photos_qty),'')::integer,nullif(btrim(product_weight_g),'')::integer,
       nullif(btrim(product_length_cm),'')::integer,nullif(btrim(product_height_cm),'')::integer,
       nullif(btrim(product_width_cm),'')::integer,_source_file FROM raw.products;
INSERT INTO core.order_statuses SELECT DISTINCT nullif(btrim(order_status),'') FROM raw.orders;
INSERT INTO core.orders
SELECT nullif(btrim(order_id),''),nullif(btrim(customer_id),''),nullif(btrim(order_status),''),
       nullif(btrim(order_purchase_timestamp),'')::timestamp,nullif(btrim(order_approved_at),'')::timestamp,
       nullif(btrim(order_delivered_carrier_date),'')::timestamp,nullif(btrim(order_delivered_customer_date),'')::timestamp,
       nullif(btrim(order_estimated_delivery_date),'')::timestamp,_source_file FROM raw.orders;
INSERT INTO core.order_items
SELECT nullif(btrim(order_id),''),nullif(btrim(order_item_id),'')::integer,
       nullif(btrim(product_id),''),nullif(btrim(seller_id),''),nullif(btrim(shipping_limit_date),'')::timestamp,
       nullif(btrim(price),'')::numeric,nullif(btrim(freight_value),'')::numeric,_source_file FROM raw.order_items;
INSERT INTO core.order_payments
SELECT nullif(btrim(order_id),''),nullif(btrim(payment_sequential),'')::integer,
       nullif(btrim(payment_type),''),nullif(btrim(payment_installments),'')::integer,
       nullif(btrim(payment_value),'')::numeric,_source_file FROM raw.order_payments;
INSERT INTO core.order_reviews
SELECT nullif(btrim(review_id),''),nullif(btrim(order_id),''),nullif(btrim(review_score),'')::smallint,
       nullif(review_comment_title,''),nullif(review_comment_message,''),nullif(btrim(review_creation_date),'')::timestamp,
       nullif(btrim(review_answer_timestamp),'')::timestamp,_source_file FROM raw.order_reviews;
