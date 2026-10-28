-- Чек с доставкой сначала считается на уровне целого заказа.
-- В исходнике одна запись order_items = единица. Для отчёта логическая строка
-- объединяет одинаковые product/seller/price/freight/shipping_limit внутри заказа.
-- Источник не даёт ID исходной строки корзины; это явно выбранная группировка.
SELECT round(avg(order_amount), 2) AS average_order_amount,
       round(avg(logical_lines), 4) AS average_lines,
       round(avg(units), 4) AS average_units
FROM mart.order_totals WHERE is_delivered;
