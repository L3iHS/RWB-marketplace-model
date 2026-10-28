WITH selected_orders AS (
    SELECT * FROM mart.order_totals
    WHERE is_delivered
      [[AND purchased_at >= CAST({{date_from}} AS date)]]
      [[AND purchased_at < CAST({{date_to}} AS date) + INTERVAL '1 day']]
      [[AND customer_state = {{customer_state}}]]
)
, months AS (
    SELECT DISTINCT month FROM core.calendar
    WHERE TRUE
      [[AND month >= date_trunc('month', CAST({{date_from}} AS date))]]
      [[AND month <= date_trunc('month', CAST({{date_to}} AS date))]]
), totals AS (
    SELECT purchase_month AS month, SUM(goods_amount) AS revenue_brl,
           COUNT(*) AS delivered_orders, AVG(order_amount) AS average_check_brl
    FROM selected_orders GROUP BY purchase_month
)
SELECT m.month, COALESCE(t.revenue_brl, 0) AS revenue_brl,
       COALESCE(t.delivered_orders, 0) AS delivered_orders, t.average_check_brl
FROM months m LEFT JOIN totals t USING (month) ORDER BY m.month;
