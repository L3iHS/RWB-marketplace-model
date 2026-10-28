WITH selected_orders AS (
    SELECT * FROM mart.order_totals
    WHERE is_delivered
      [[AND purchased_at >= CAST({{date_from}} AS date)]]
      [[AND purchased_at < CAST({{date_to}} AS date) + INTERVAL '1 day']]
      [[AND customer_state = {{customer_state}}]]
)
SELECT c.category_key, c.name, SUM(d.price) AS revenue_brl,
       100 * SUM(d.price) / NULLIF(SUM(SUM(d.price)) OVER (), 0) AS revenue_pct
FROM mart.delivered_items d
JOIN selected_orders o USING (order_id)
JOIN core.categories c USING (category_key)
GROUP BY c.category_key, c.name ORDER BY revenue_brl DESC, c.category_key;
