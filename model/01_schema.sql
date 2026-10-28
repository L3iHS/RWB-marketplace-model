-- Структура core. Схема пересоздаётся с нуля на каждой сборке.
--
-- У каждой таблицы в комментарии указан уровень: что означает одна строка.
-- Ключи и ограничения проверяет сам PostgreSQL: если данные их нарушат,
-- сборка упадёт, и транзакция откатится.
--
-- source_file / loaded_at — служебные поля происхождения строки из raw.
-- source_file заполняет загрузчик; при ручной вставке в raw (в тестах) он пуст.

-- Покупатель-человек. Одна строка = один customer_unique_id.
-- customer_id из источника выдаётся на каждый заказ, поэтому людей по нему не считаем.
CREATE TABLE core.customers (
    customer_unique_id text PRIMARY KEY
);

-- Адресная запись покупателя для конкретного заказа. Одна строка = один customer_id.
-- Адрес хранится здесь, а не в customers: у одного человека заказы
-- могут уходить по разным адресам.
CREATE TABLE core.customer_order_profiles (
    customer_id        text PRIMARY KEY,
    customer_unique_id text NOT NULL REFERENCES core.customers,
    zip_code_prefix    text,
    city               text,
    state              text
);

-- Справочник статусов. Одна строка = один статус заказа.
-- is_delivered — единственное место, где задано правило выручки:
-- выручкой считаются только доставленные заказы.
CREATE TABLE core.order_statuses (
    status_code  text PRIMARY KEY,
    is_delivered boolean NOT NULL
);

-- Категория товара. Одна строка = одна исходная категория,
-- плюс одна строка '__unknown__' для товаров без категории.
-- category_key — исходное португальское название: оно стабильно между сборками
-- и понятно в отчётах. Для товаров без категории — '__unknown__'.
-- name — подпись для отчётов: перевод, если есть, иначе исходное название,
-- иначе 'unknown'. Правило задано один раз здесь, а не в каждом запросе.
CREATE TABLE core.categories (
    category_key text PRIMARY KEY,
    name_pt      text UNIQUE,
    name_en      text,
    is_unknown   boolean GENERATED ALWAYS AS (name_pt IS NULL) STORED,
    name         text GENERATED ALWAYS AS (coalesce(name_en, name_pt, 'unknown')) STORED,
    CHECK (category_key = coalesce(name_pt, '__unknown__'))
);

-- Карточка товара. Одна строка = один product_id.
CREATE TABLE core.products (
    product_id         text PRIMARY KEY,
    category_key       text NOT NULL REFERENCES core.categories,
    name_length        integer,
    description_length integer,
    photos_qty         integer,
    weight_g           integer,
    length_cm          integer,
    height_cm          integer,
    width_cm           integer
);

-- Продавец. Одна строка = один seller_id.
CREATE TABLE core.sellers (
    seller_id       text PRIMARY KEY,
    zip_code_prefix text,
    city            text,
    state           text
);

-- Заказ. Одна строка = один заказ любого статуса, включая отменённые:
-- фильтр по статусу применяется в витринах, а не при загрузке.
-- Время — исходное локальное, без часового пояса: его не додумываем.
CREATE TABLE core.orders (
    order_id              text PRIMARY KEY,
    customer_id           text NOT NULL REFERENCES core.customer_order_profiles,
    status_code           text NOT NULL REFERENCES core.order_statuses,
    purchased_at          timestamp NOT NULL,
    approved_at           timestamp,
    delivered_carrier_at  timestamp,
    delivered_customer_at timestamp,
    estimated_delivery_at timestamp,
    source_file           text,
    loaded_at             timestamptz NOT NULL
);

-- Позиция заказа. Одна строка = одна единица товара:
-- три одинаковых товара в заказе — это три строки (order_item_id 1, 2, 3).
CREATE TABLE core.order_items (
    order_id          text NOT NULL REFERENCES core.orders,
    order_item_id     integer NOT NULL CHECK (order_item_id > 0),
    product_id        text NOT NULL REFERENCES core.products,
    seller_id         text NOT NULL REFERENCES core.sellers,
    shipping_limit_at timestamp,
    -- Верхняя граница исключает Infinity и NaN, которые PostgreSQL считает больше конечных чисел.
    price             numeric NOT NULL CHECK (price >= 0 AND price < 'Infinity'::numeric),
    freight_value     numeric NOT NULL CHECK (freight_value >= 0 AND freight_value < 'Infinity'::numeric),
    source_file       text,
    loaded_at         timestamptz NOT NULL,
    PRIMARY KEY (order_id, order_item_id)
);

-- Платёж. Одна строка = одна платёжная запись заказа.
-- Заказ можно оплатить несколькими способами (payment_sequential 1, 2, ...).
-- installments — число частей рассрочки, а не множитель суммы:
-- payment_value уже содержит полную сумму записи.
CREATE TABLE core.order_payments (
    order_id           text NOT NULL REFERENCES core.orders,
    payment_sequential integer NOT NULL CHECK (payment_sequential > 0),
    payment_type       text NOT NULL,
    installments       integer NOT NULL CHECK (installments >= 0),
    payment_value      numeric NOT NULL CHECK (payment_value >= 0 AND payment_value < 'Infinity'::numeric),
    source_file        text,
    loaded_at          timestamptz NOT NULL,
    PRIMARY KEY (order_id, payment_sequential)
);

-- Отзыв. Одна строка = один отзыв на один заказ.
-- Ни review_id, ни order_id по отдельности не уникальны, поэтому ключ — пара.
CREATE TABLE core.order_reviews (
    review_id       text NOT NULL,
    order_id        text NOT NULL REFERENCES core.orders,
    score           integer NOT NULL CHECK (score BETWEEN 1 AND 5),
    comment_title   text,
    comment_message text,
    created_at      timestamp,
    answered_at     timestamp,
    source_file     text,
    loaded_at       timestamptz NOT NULL,
    PRIMARY KEY (review_id, order_id)
);

-- Календарь. Одна строка = один день.
-- Отчёты по периодам строим от календаря через LEFT JOIN, поэтому
-- месяц без заказов (ноябрь 2016) не пропадает, а показывается с нулём.
CREATE TABLE core.calendar (
    date        date PRIMARY KEY,
    month       date NOT NULL,  -- первый день месяца, ключ для помесячных отчётов
    year        integer NOT NULL,
    month_num   integer NOT NULL,
    day_of_week integer NOT NULL,  -- 1 = понедельник, 7 = воскресенье
    is_weekend  boolean NOT NULL
);

-- Индексы по колонкам, по которым соединяем и фильтруем.
-- Первичные ключи индексируются автоматически.
CREATE INDEX ON core.customer_order_profiles (customer_unique_id);
CREATE INDEX ON core.products (category_key);
CREATE INDEX ON core.orders (customer_id);
CREATE INDEX ON core.orders (purchased_at);
CREATE INDEX ON core.order_items (product_id);
CREATE INDEX ON core.order_items (seller_id);
CREATE INDEX ON core.order_reviews (order_id);
