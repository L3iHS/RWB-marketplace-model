-- До изменения core: проверяем контракт источника и называем место ошибки.
-- DO запускает блок PL/pgSQL: здесь удобны циклы по спискам правил.
-- RAISE EXCEPTION прерывает сборку; внешняя транзакция откатывается целиком.
-- В format(): %I безопасно подставляет имя таблицы/колонки, %L — значение.
-- EXECUTE ... INTO сохраняет результат динамического запроса в переменную.
DO $$
DECLARE
    rule record;
    field text;
    key_sql text;
    bad_count bigint;
    example text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM raw.orders) THEN
        RAISE EXCEPTION 'raw.orders пуст: сначала загрузите исходные данные';
    END IF;

    -- 1. Обязательные поля: NULL, пустая строка и одни пробелы недопустимы.
    -- Необязательные даты/описания сюда специально не включены.
    FOR rule IN SELECT * FROM (VALUES
        ('orders', ARRAY['order_id','customer_id','order_status','order_purchase_timestamp','_source_file']),
        ('customers', ARRAY['customer_id','customer_unique_id']),
        ('products', ARRAY['product_id']),
        ('sellers', ARRAY['seller_id']),
        ('order_items', ARRAY['order_id','order_item_id','product_id','seller_id','price','freight_value','_source_file']),
        ('order_payments', ARRAY['order_id','payment_sequential','payment_type','payment_installments','payment_value','_source_file']),
        ('order_reviews', ARRAY['review_id','order_id','review_score','_source_file']),
        ('product_category_translation', ARRAY['product_category_name'])
    ) AS rules(table_name, fields)
    LOOP
        FOREACH field IN ARRAY rule.fields LOOP
            EXECUTE format('SELECT count(*) FROM raw.%I WHERE nullif(btrim(%I), '''') IS NULL', rule.table_name, field) INTO bad_count;
            IF bad_count > 0 THEN
                RAISE EXCEPTION 'Пустое обязательное поле raw.%.%: % строк', rule.table_name, field, bad_count;
            END IF;
        END LOOP;
    END LOOP;

    -- 2. Прежде чем делать ::timestamp/::numeric в загрузке, проверяем тип.
    -- pg_input_is_valid не роняет запрос на первом некорректном значении.
    FOR rule IN SELECT * FROM (VALUES
        ('orders','order_purchase_timestamp','timestamp'),
        ('orders','order_approved_at','timestamp'),
        ('orders','order_delivered_carrier_date','timestamp'),
        ('orders','order_delivered_customer_date','timestamp'),
        ('orders','order_estimated_delivery_date','timestamp'),
        ('order_items','order_item_id','integer'),
        ('order_items','shipping_limit_date','timestamp'),
        ('order_items','price','numeric'), ('order_items','freight_value','numeric'),
        ('order_payments','payment_sequential','integer'),
        ('order_payments','payment_installments','integer'),
        ('order_payments','payment_value','numeric'),
        ('order_reviews','review_score','integer'),
        ('order_reviews','review_creation_date','timestamp'),
        ('order_reviews','review_answer_timestamp','timestamp'),
        ('products','product_name_lenght','integer'),
        ('products','product_description_lenght','integer'),
        ('products','product_photos_qty','integer'),
        ('products','product_weight_g','integer'),
        ('products','product_length_cm','integer'),
        ('products','product_height_cm','integer'),
        ('products','product_width_cm','integer')
    ) AS rules(table_name, column_name, target_type)
    LOOP
        EXECUTE format('SELECT %I FROM raw.%I WHERE nullif(btrim(%I), '''') IS NOT NULL AND NOT pg_input_is_valid(%I, %L) LIMIT 1',
            rule.column_name, rule.table_name, rule.column_name, rule.column_name, rule.target_type) INTO example;
        IF example IS NOT NULL THEN
            RAISE EXCEPTION 'Некорректный тип % в raw.%.%: %', rule.target_type, rule.table_name, rule.column_name, left(example, 80);
        END IF;
    END LOOP;

    -- 3. Кандидатные ключи: не объявляем ключом колонку только по её имени.
    -- У позиций, платежей и отзывов уникальность проверяется по паре полей.
    FOR rule IN SELECT * FROM (VALUES
        ('orders', ARRAY['order_id']), ('customers', ARRAY['customer_id']),
        ('products', ARRAY['product_id']), ('sellers', ARRAY['seller_id']),
        ('order_items', ARRAY['order_id','order_item_id']),
        ('order_payments', ARRAY['order_id','payment_sequential']),
        ('order_reviews', ARRAY['review_id','order_id']),
        ('product_category_translation', ARRAY['product_category_name'])
    ) AS rules(table_name, fields)
    LOOP
        SELECT string_agg(format('%I', f), ', ') INTO key_sql FROM unnest(rule.fields) AS f;
        EXECUTE format('SELECT count(*) FROM (SELECT 1 FROM raw.%I GROUP BY %s HAVING count(*)>1) d', rule.table_name, key_sql) INTO bad_count;
        IF bad_count > 0 THEN
            RAISE EXCEPTION 'Повтор ключа raw.% (%): % групп. Строки автоматически не удаляются', rule.table_name, key_sql, bad_count;
        END IF;
    END LOOP;

    -- Проверяем весь набор, без LIMIT 1: на свежем raw план с LIMIT мог
    -- выбирать вложенные циклы и многократно сканировать большие таблицы.
    FOR rule IN SELECT * FROM (VALUES
        ('orders','customer_id','customers','customer_id'),
        ('order_items','order_id','orders','order_id'),
        ('order_items','product_id','products','product_id'),
        ('order_items','seller_id','sellers','seller_id'),
        ('order_payments','order_id','orders','order_id'),
        ('order_reviews','order_id','orders','order_id')
    ) AS rules(child_table, child_key, parent_table, parent_key)
    LOOP
        EXECUTE format('SELECT min(c.%I) FROM raw.%I c WHERE NOT EXISTS (SELECT 1 FROM raw.%I p WHERE c.%I=p.%I)',
            rule.child_key, rule.child_table, rule.parent_table, rule.child_key, rule.parent_key) INTO example;
        IF example IS NOT NULL THEN
            RAISE EXCEPTION 'Нет связи raw.%.% -> raw.%.%; значение: %',
                rule.child_table, rule.child_key, rule.parent_table, rule.parent_key, left(example, 80);
        END IF;
    END LOOP;

    -- numeric допускает NaN/Infinity: в денежных суммах их принимать нельзя.
    IF EXISTS (SELECT 1 FROM raw.order_items WHERE price::numeric::text IN ('NaN','Infinity','-Infinity') OR freight_value::numeric::text IN ('NaN','Infinity','-Infinity'))
       OR EXISTS (SELECT 1 FROM raw.order_payments WHERE payment_value::numeric::text IN ('NaN','Infinity','-Infinity')) THEN
        RAISE EXCEPTION 'Денежная сумма должна быть конечным числом: обнаружен NaN/Infinity';
    END IF;
END $$;
