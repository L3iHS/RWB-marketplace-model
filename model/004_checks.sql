-- Проверки зависят от источника, а не от фиксированного размера снимка Olist.
-- Эти проверки — инварианты переноса, а не подстановка контрольных чисел.
-- 99 441 заказ и выручка 13 221 498,11 проверяются отдельно для снимка Olist.
-- Здесь сравниваем core с текущим raw, чтобы принять и новые корректные строки.
DO $$
DECLARE
    pair record;
    source_count bigint;
    target_count bigint;
BEGIN
    -- 1. Там, где перенос один-к-одному, число строк должно сохраниться.
    FOR pair IN SELECT * FROM (VALUES
        ('customers', 'customer_order_profiles'), ('orders', 'orders'),
        ('order_items', 'order_items'), ('order_payments', 'order_payments'),
        ('order_reviews', 'order_reviews'), ('products', 'products'), ('sellers', 'sellers')
    ) AS pairs(source_table, target_table)
    LOOP
        EXECUTE format('SELECT count(*) FROM raw.%I', pair.source_table) INTO source_count;
        EXECUTE format('SELECT count(*) FROM core.%I', pair.target_table) INTO target_count;
        IF source_count <> target_count THEN
            RAISE EXCEPTION 'Потеря/размножение строк % -> %: % != %', pair.source_table, pair.target_table, source_count, target_count;
        END IF;
    END LOOP;
    -- 2. Люди выделяются из профилей: здесь сравниваем distinct ID, не строки.
    IF (SELECT count(*) FROM core.customers) <>
       (SELECT count(DISTINCT customer_unique_id) FROM raw.customers) THEN
        RAISE EXCEPTION 'Не сохранено количество уникальных покупателей';
    END IF;
    IF (SELECT count(*) FROM raw.orders)=0 THEN
        RAISE EXCEPTION 'raw.orders пуст: сначала загрузите исходные данные';
    END IF;
    IF EXISTS (
        SELECT 1 FROM raw.product_category_translation t
        WHERE NOT EXISTS (SELECT 1 FROM core.categories c
            WHERE c.name_pt=t.product_category_name AND c.name_en IS NOT DISTINCT FROM nullif(t.product_category_name_english,''))
    ) THEN
        RAISE EXCEPTION 'Потеряны переводы категорий';
    END IF;
    IF EXISTS (
        SELECT 1 FROM raw.products p
        WHERE NOT EXISTS (SELECT 1 FROM core.products cp JOIN core.categories c USING(category_id)
            WHERE cp.product_id=p.product_id AND c.name_pt IS NOT DISTINCT FROM nullif(p.product_category_name,''))
    ) THEN
        RAISE EXCEPTION 'Категория товара отличается от источника';
    END IF;
    -- 3. Число строк само по себе не защищает от потери/удвоения денег.
    -- Сверяем три независимые суммы: товары, доставка и платежи.
    IF (SELECT sum(price::numeric) FROM raw.order_items) IS DISTINCT FROM (SELECT sum(price) FROM core.order_items)
       OR (SELECT sum(freight_value::numeric) FROM raw.order_items) IS DISTINCT FROM (SELECT sum(freight_value) FROM core.order_items)
       OR (SELECT sum(payment_value::numeric) FROM raw.order_payments) IS DISTINCT FROM (SELECT sum(payment_value) FROM core.order_payments) THEN
        RAISE EXCEPTION 'Суммы raw и core расходятся';
    END IF;
    -- 4. Витрина должна сохранять по одной строке на заказ и суммы фактов.
    IF (SELECT count(*) FROM mart.order_totals) <> (SELECT count(*) FROM core.orders) THEN
        RAISE EXCEPTION 'Витрина размножила/потеряла заказы';
    END IF;
    IF (SELECT sum(goods_amount) FROM mart.order_totals) IS DISTINCT FROM (SELECT sum(price) FROM core.order_items)
       OR (SELECT sum(paid_amount) FROM mart.order_totals) IS DISTINCT FROM (SELECT sum(payment_value) FROM core.order_payments) THEN
        RAISE EXCEPTION 'Суммы витрины заказов не совпадают с фактами';
    END IF;
END $$;
-- ANALYZE собирает статистику для планировщика, не меняя бизнес-данные.
ANALYZE core.customers;
ANALYZE core.customer_order_profiles;
ANALYZE core.categories;
ANALYZE core.products;
ANALYZE core.sellers;
ANALYZE core.orders;
ANALYZE core.order_items;
ANALYZE core.order_payments;
ANALYZE core.order_reviews;
