-- A3: среднее сумм заказа (товары + доставка), каждый доставленный заказ весит один раз.
SELECT round(avg(order_total),2) AS average_order_value,
       round(avg(item_rows),4) AS average_item_rows,
       round(avg(units),4) AS average_units,
       count(*) AS delivered_orders,
       count(order_total) AS orders_with_known_total
FROM mart.order_summary WHERE order_status='delivered';
