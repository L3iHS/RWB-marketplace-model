-- Инварианты модели, не привязанные к контрольным суммам конкретной выгрузки.
DO $$
DECLARE pair text[]; raw_count bigint; core_count bigint;
BEGIN
  FOREACH pair SLICE 1 IN ARRAY ARRAY[
    ['customers','customer_profiles'],['orders','orders'],['order_items','order_items'],
    ['order_payments','order_payments'],['order_reviews','order_reviews'],['products','products'],['sellers','sellers']
  ] LOOP
    EXECUTE format('SELECT count(*) FROM raw.%I',pair[1]) INTO raw_count;
    EXECUTE format('SELECT count(*) FROM core.%I',pair[2]) INTO core_count;
    IF raw_count<>core_count THEN
      RAISE EXCEPTION 'Потеря строк % -> %: % -> %',pair[1],pair[2],raw_count,core_count;
    END IF;
  END LOOP;
  ASSERT (SELECT count(*) FROM core.buyers)=(SELECT count(DISTINCT nullif(btrim(customer_unique_id),'')) FROM raw.customers), 'Потеря покупателей';
  ASSERT (SELECT count(*) FROM mart.order_summary)=(SELECT count(*) FROM core.orders), 'Размножение/потеря заказов';
  ASSERT (SELECT sum(price) FROM core.order_items) IS NOT DISTINCT FROM (SELECT sum(price::numeric) FROM raw.order_items), 'Изменение цен';
  ASSERT (SELECT sum(freight_value) FROM core.order_items) IS NOT DISTINCT FROM (SELECT sum(freight_value::numeric) FROM raw.order_items), 'Изменение доставки';
  ASSERT (SELECT sum(payment_value) FROM core.order_payments) IS NOT DISTINCT FROM (SELECT sum(payment_value::numeric) FROM raw.order_payments), 'Изменение платежей';
  ASSERT (SELECT sum(price) FROM mart.sales_items) IS NOT DISTINCT FROM (SELECT sum(revenue) FROM mart.category_sales), 'Потеря категорий';
  ASSERT (SELECT sum(price) FROM mart.sales_items) IS NOT DISTINCT FROM (SELECT sum(revenue) FROM mart.seller_sales), 'Потеря продавцов';
  ASSERT (SELECT sum(price) FROM mart.sales_items) IS NOT DISTINCT FROM (SELECT sum(goods_total) FROM mart.order_summary WHERE order_status='delivered'), 'Ошибка уровня заказа';
  ASSERT (SELECT sum(payment_count) FROM mart.order_summary)=(SELECT count(*) FROM core.order_payments), 'Размножение платежей';
  ASSERT (SELECT sum(review_count) FROM mart.order_summary)=(SELECT count(*) FROM core.order_reviews), 'Размножение отзывов';
  ASSERT NOT EXISTS(SELECT 1 FROM mart.quality_issues WHERE severity='error'), 'Критическая проблема качества данных';
END $$;
SELECT severity,issue_code,count(*) AS records FROM mart.quality_issues GROUP BY 1,2 ORDER BY 1,2;
