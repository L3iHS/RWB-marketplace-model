CREATE TABLE core.buyers (
    buyer_id text PRIMARY KEY CHECK (buyer_id <> '')
);
CREATE TABLE core.customer_profiles (
    customer_id text PRIMARY KEY CHECK (customer_id <> ''),
    buyer_id text NOT NULL REFERENCES core.buyers,
    zip_code_prefix text,
    city text,
    state text,
    source_file text
);
COMMENT ON TABLE core.customer_profiles IS 'Запись покупателя из источника с адресным контекстом заказа; не текущий адрес человека.';
CREATE INDEX ON core.customer_profiles(buyer_id);
CREATE TABLE core.sellers (
    seller_id text PRIMARY KEY CHECK (seller_id <> ''),
    zip_code_prefix text,
    city text,
    state text,
    source_file text
);
CREATE TABLE core.categories (
    category_key text PRIMARY KEY,
    name_pt text UNIQUE,
    name_en text,
    is_unknown boolean NOT NULL DEFAULT false,
    CHECK (is_unknown = (name_pt IS NULL))
);
COMMENT ON TABLE core.categories IS 'Категории из товаров и переводов, включая явную неизвестную категорию. Перевод не является ключом.';
CREATE TABLE core.products (
    product_id text PRIMARY KEY CHECK (product_id <> ''),
    category_key text NOT NULL REFERENCES core.categories,
    name_length integer,
    description_length integer,
    photos_qty integer,
    weight_g integer,
    length_cm integer,
    height_cm integer,
    width_cm integer,
    source_file text
);
CREATE INDEX ON core.products(category_key);
CREATE TABLE core.order_statuses (
    order_status text PRIMARY KEY CHECK (order_status <> '')
);
CREATE TABLE core.orders (
    order_id text PRIMARY KEY CHECK (order_id <> ''),
    customer_id text NOT NULL REFERENCES core.customer_profiles,
    order_status text NOT NULL REFERENCES core.order_statuses,
    purchased_at timestamp NOT NULL,
    approved_at timestamp,
    delivered_carrier_at timestamp,
    delivered_customer_at timestamp,
    estimated_delivery_at timestamp,
    source_file text
);
COMMENT ON COLUMN core.orders.purchased_at IS 'Исходное локальное время без timezone; часовой пояс не восстанавливается по догадке.';
CREATE INDEX ON core.orders(customer_id);
CREATE INDEX ON core.orders(purchased_at);
CREATE TABLE core.order_items (
    order_id text NOT NULL REFERENCES core.orders,
    item_number integer NOT NULL CHECK (item_number > 0),
    product_id text NOT NULL REFERENCES core.products,
    seller_id text NOT NULL REFERENCES core.sellers,
    shipping_limit_at timestamp,
    price numeric NOT NULL CHECK (price >= 0),
    freight_value numeric NOT NULL CHECK (freight_value >= 0),
    source_file text,
    PRIMARY KEY (order_id,item_number)
);
COMMENT ON TABLE core.order_items IS 'Одна строка источника — одна единица товара. item_number — номер внутри заказа, не количество.';
CREATE INDEX ON core.order_items(product_id);
CREATE INDEX ON core.order_items(seller_id);
CREATE TABLE core.order_payments (
    order_id text NOT NULL REFERENCES core.orders,
    payment_number integer NOT NULL CHECK (payment_number > 0),
    payment_type text NOT NULL CHECK (payment_type <> ''),
    installments integer NOT NULL CHECK (installments >= 0),
    payment_value numeric NOT NULL CHECK (payment_value >= 0),
    source_file text,
    PRIMARY KEY (order_id,payment_number)
);
COMMENT ON COLUMN core.order_payments.installments IS 'Число частей рассрочки; payment_value уже содержит полную сумму этой записи и не умножается на installments.';
CREATE TABLE core.order_reviews (
    review_id text NOT NULL CHECK (review_id <> ''),
    order_id text NOT NULL REFERENCES core.orders,
    score smallint NOT NULL CHECK (score BETWEEN 1 AND 5),
    comment_title text,
    comment_message text,
    created_at timestamp,
    answered_at timestamp,
    source_file text,
    PRIMARY KEY (review_id,order_id)
);
COMMENT ON TABLE core.order_reviews IS 'Связь отзыва и заказа; review_id встречается у нескольких заказов. Все записи сохранены.';
CREATE INDEX ON core.order_reviews(order_id);
