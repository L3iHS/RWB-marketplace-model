-- Фикстура только для отдельной тестовой базы; весь блок защищён проверкой имени.
DO $$
BEGIN
    IF left(current_database(), 15) <> 'hack_scenarios_' THEN
        RAISE EXCEPTION 'Фикстура разрешена только в изолированной базе hack_scenarios_*';
    END IF;
-- Только для изолированной тестовой базы, никогда для рабочего marketplace.
TRUNCATE raw.orders, raw.order_items, raw.order_payments, raw.order_reviews,
         raw.customers, raw.sellers, raw.products, raw.product_category_translation;
INSERT INTO raw.customers (customer_id, customer_unique_id, customer_city, customer_state)
VALUES ('customer-1','person-1','city-one','SP'), ('customer-2','person-1','city-two','RJ');
INSERT INTO raw.sellers (seller_id, seller_city, seller_state) VALUES ('seller-1','seller-city','MG');
INSERT INTO raw.products (product_id, product_category_name) VALUES ('product-1','bbb_original'),('product-2',NULL);
INSERT INTO raw.product_category_translation VALUES ('bbb_original','Original', 'fixture.csv', now());
INSERT INTO raw.orders (order_id, customer_id, order_status, order_purchase_timestamp,
    order_approved_at, order_delivered_carrier_date, order_delivered_customer_date,
    order_estimated_delivery_date, _source_file)
VALUES ('order-1','customer-1','delivered','2017-01-01 10:00:00',
        '2017-01-01 11:00:00','2017-01-02 10:00:00','2017-01-03 10:00:00','2017-01-04','fixture.csv'),
       ('order-2','customer-2','canceled','2017-02-01 10:00:00',NULL,NULL,NULL,'2017-02-04','fixture.csv');
INSERT INTO raw.order_items (order_id,order_item_id,product_id,seller_id,price,freight_value,_source_file)
VALUES ('order-1','1','product-1','seller-1','100','10','fixture.csv'),
       ('order-1','2','product-1','seller-1','100','10','fixture.csv'),
       ('order-1','3','product-2','seller-1','50','5','fixture.csv');
INSERT INTO raw.order_payments (order_id,payment_sequential,payment_type,payment_installments,payment_value,_source_file)
VALUES ('order-1','1','credit_card','1','200','fixture.csv'),('order-1','2','voucher','1','75','fixture.csv');
INSERT INTO raw.order_reviews (review_id,order_id,review_score,_source_file)
VALUES ('shared-review','order-1','5','fixture.csv'),('shared-review','order-2','2','fixture.csv');

END $$;
