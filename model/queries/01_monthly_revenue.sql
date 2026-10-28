-- Месяц оформления; только доставленные заказы; товары без доставки.
WITH months AS (
    SELECT generate_series('2016-09-01'::timestamp, '2018-08-01'::timestamp, interval '1 month')::date AS month
)
SELECT m.month, count(o.order_id) AS orders,
       coalesce(sum(o.goods_amount), 0) AS revenue
FROM months m LEFT JOIN mart.order_totals o
    ON o.purchased_at >= m.month AND o.purchased_at < m.month + interval '1 month'
    AND o.is_delivered
GROUP BY m.month ORDER BY m.month;
