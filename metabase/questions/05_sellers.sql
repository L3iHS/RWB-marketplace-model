WITH selected_orders AS (
    SELECT * FROM mart.order_totals
    WHERE is_delivered
      [[AND purchased_at >= CAST({{date_from}} AS date)]]
      [[AND purchased_at < CAST({{date_to}} AS date) + INTERVAL '1 day']]
      [[AND customer_state = {{customer_state}}]]
)
SELECT d.seller_id, s.city, s.state,
       SUM(d.price) AS revenue_brl, COUNT(DISTINCT d.order_id) AS orders
FROM mart.delivered_items d
JOIN selected_orders o USING (order_id)
JOIN core.sellers s USING (seller_id)
GROUP BY d.seller_id, s.city, s.state
ORDER BY revenue_brl DESC, d.seller_id LIMIT 10;
