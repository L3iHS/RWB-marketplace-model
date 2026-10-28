-- Пояснения видны в DBeaver в свойствах таблиц и колонок.
COMMENT ON SCHEMA core IS 'Проверенная модель команды: сущности и подробные факты. Одна строка всегда имеет определённый смысл.';
COMMENT ON SCHEMA mart IS 'Готовые представления для отчётов: заказы, продажи по позициям, диагностика.';
COMMENT ON TABLE core.customer_order_profiles IS 'Исходная адресная запись customer_id. Связывает заказ с человеком и адресом именно этой записи.';
COMMENT ON TABLE core.products IS 'Одна карточка товара. Цена продажи находится в позиции заказа, не здесь.';
COMMENT ON TABLE core.sellers IS 'Один продавец и его география в исходном снимке.';
COMMENT ON TABLE core.payment_types IS 'Способы оплаты из источника; несколько способов могут использоваться в одном заказе.';
COMMENT ON VIEW mart.order_totals IS 'Одна строка = заказ. Позиции и платежи агрегированы раздельно; отсутствующая сумма остаётся NULL.';
COMMENT ON VIEW mart.delivered_items IS 'Одна строка = одна единица товара доставленного заказа. Цена без доставки используется как выручка кейса.';
COMMENT ON VIEW mart.quality_issues IS 'Одна строка = одно предупреждение о сущности. Один заказ может иметь несколько предупреждений.';

DO $$
DECLARE r record;
BEGIN
    FOR r IN SELECT * FROM (VALUES
        ('customers','customer_unique_id','Устойчивый исходный ID человека; по нему считаем повторные оформления.'),
        ('customer_order_profiles','customer_id','Исходный ID адресной записи, используемый в заказе; не устойчивый ID человека.'),
        ('customer_order_profiles','customer_unique_id','Ссылка на человека; у одного человека может быть несколько customer_id.'),
        ('customer_order_profiles','zip_code_prefix','Почтовый префикс покупателя в этой записи; текст сохраняет ведущие нули.'),
        ('customer_order_profiles','city','Город покупателя из записи, связанной с заказом.'),
        ('customer_order_profiles','state','Штат покупателя из записи, связанной с заказом.'),
        ('order_statuses','status_code','Исходный статус. Новые значения сохраняются, но требуют проверки.'),
        ('order_statuses','is_delivered','Признак delivered; только эти заказы участвуют в выручке кейса.'),
        ('payment_types','payment_type','Код способа оплаты, например credit_card или voucher.'),
        ('categories','category_id','Постоянный ключ в этой базе. Категории не очищаются при пересборке; резервная копия должна сохранять их соответствия.'),
        ('categories','name_pt','Исходное название категории. Единственный NULL означает отсутствие категории.'),
        ('categories','name_en','Перевод; NULL не означает отсутствие самой категории.'),
        ('products','product_id','Исходный ID карточки товара; один товар может продаваться в разных заказах.'),
        ('products','category_id','Категория товара в текущем снимке, включая отдельную группу без категории.'),
        ('products','name_length','Длина названия; исправлено исходное написание product_name_lenght.'),
        ('products','description_length','Длина описания; исправлено исходное написание product_description_lenght.'),
        ('products','photos_qty','Число фотографий в карточке.'),
        ('products','weight_g','Вес в граммах; NULL — неизвестен.'),
        ('products','length_cm','Длина в сантиметрах; NULL — неизвестна.'),
        ('products','height_cm','Высота в сантиметрах; NULL — неизвестна.'),
        ('products','width_cm','Ширина в сантиметрах; NULL — неизвестна.'),
        ('sellers','seller_id','Исходный устойчивый ID продавца.'),
        ('sellers','zip_code_prefix','Почтовый префикс продавца, текст.'),
        ('sellers','city','Город продавца; отличается от города покупателя.'),
        ('sellers','state','Штат продавца; отличается от штата покупателя.'),
        ('orders','order_id','ID заказа. Одна строка orders — один заказ любого статуса.'),
        ('orders','customer_id','Ссылка на исходный адресный профиль; человек доступен через customer_unique_id.'),
        ('orders','status_code','Статус заказа на момент выгрузки, не история переходов.'),
        ('orders','purchased_at','Дата оформления; по ней группируем месячный отчёт.'),
        ('orders','approved_at','Подтверждение оплаты; NULL означает отсутствие даты в источнике.'),
        ('orders','delivered_carrier_at','Передача перевозчику; относится к заказу целиком.'),
        ('orders','delivered_customer_at','Вручение покупателю; может отсутствовать даже при delivered.'),
        ('orders','estimated_delivery_at','Обещанная дата доставки; для просрочки сравнивать календарные даты.'),
        ('order_items','order_id','Заказ, содержащий эту единицу товара; часть составного ключа.'),
        ('order_items','order_item_id','Номер единицы внутри заказа; глобально не уникален.'),
        ('order_items','product_id','Какой товар куплен.'),
        ('order_items','seller_id','Кто продал именно эту единицу; в заказе возможны разные продавцы.'),
        ('order_items','shipping_limit_at','Крайний срок отгрузки позиции продавцом.'),
        ('order_items','price','Стоимость одной единицы без доставки; основа выручки доставленных заказов.'),
        ('order_items','freight_value','Стоимость доставки этой единицы; входит в чек, не в выручку кейса.'),
        ('order_payments','order_id','Оплачиваемый заказ; часть составного ключа.'),
        ('order_payments','payment_sequential','Номер платёжной записи внутри заказа; не номер части рассрочки.'),
        ('order_payments','payment_type','Способ оплаты этой записью.'),
        ('order_payments','installments','Число частей рассрочки, включая исходные нули. Не умножать на payment_value.'),
        ('order_payments','payment_value','Полная сумма этой платёжной записи, точный numeric.'),
        ('order_reviews','review_id','Исходный ID отзыва. Повторяется у разных заказов; часть составного ключа.'),
        ('order_reviews','order_id','Заказ отзыва. Один заказ может иметь несколько отзывов.'),
        ('order_reviews','score','Оценка от 1 до 5.'),
        ('order_reviews','comment_title','Заголовок отзыва, исходный текст без переписывания.'),
        ('order_reviews','comment_message','Текст отзыва; отсутствие текста не удаляет оценку.'),
        ('order_reviews','created_at','Дата создания из источника.'),
        ('order_reviews','answered_at','Время ответа на опрос из источника.')
    ) AS notes(table_name, column_name, description)
    LOOP
        EXECUTE format('COMMENT ON COLUMN core.%I.%I IS %L', r.table_name, r.column_name, r.description);
    END LOOP;
    FOR r IN SELECT unnest(ARRAY['orders','order_items','order_payments','order_reviews']) AS table_name
    LOOP
        EXECUTE format('COMMENT ON COLUMN core.%I.source_file IS %L', r.table_name, 'Имя исходного CSV для трассировки записи.');
        EXECUTE format('COMMENT ON COLUMN core.%I.source_loaded_at IS %L', r.table_name, 'Время загрузки в raw, не время бизнес-события и не время сборки core.');
    END LOOP;
END $$;
COMMENT ON COLUMN mart.order_totals.units IS 'Число исходных строк позиций = число единиц. NULL — позиций нет, а не доказанное нулевое количество.';
COMMENT ON COLUMN mart.order_totals.analytical_lines IS 'Число различных пар товар/продавец. Дополнительная метрика; не число строк исходного файла.';
COMMENT ON COLUMN mart.order_totals.goods_amount IS 'Сумма цен товаров без доставки. Для выручки отбирать is_delivered=true.';
COMMENT ON COLUMN mart.order_totals.freight_amount IS 'Сумма доставки позиций заказа.';
COMMENT ON COLUMN mart.order_totals.order_amount IS 'Стоимость товаров с доставкой на уровне заказа. Основа среднего чека.';
COMMENT ON COLUMN mart.order_totals.payment_records IS 'Количество платёжных записей, не частей рассрочки.';
COMMENT ON COLUMN mart.order_totals.paid_amount IS 'Сумма payment_value; может расходиться с order_amount.';
COMMENT ON COLUMN mart.quality_issues.issue_code IS 'Код предупреждения, например payment_amount_mismatch; не все предупреждения означают ошибку бизнеса.';
COMMENT ON COLUMN mart.quality_issues.entity_type IS 'Тип сущности: order, product или payment.';
COMMENT ON COLUMN mart.quality_issues.entity_id IS 'Идентификатор сущности для расследования.';
COMMENT ON COLUMN mart.quality_issues.order_id IS 'ID заказа, если предупреждение относится к заказу/платежу.';
COMMENT ON COLUMN mart.quality_issues.details IS 'Причина предупреждения и доступные исходные значения.';

COMMENT ON COLUMN mart.order_totals.logical_lines IS 'Число логических строк: различные товар/продавец/цена/доставка/срок отгрузки внутри заказа. Повторные одинаковые единицы объединены только при подсчёте строк, core сохраняет их отдельно.';
