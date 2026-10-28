WITH selected_orders AS (
    SELECT * FROM mart.order_totals
    WHERE is_delivered
      [[AND purchased_at >= CAST({{date_from}} AS date)]]
      [[AND purchased_at < CAST({{date_to}} AS date) + INTERVAL '1 day']]
      [[AND customer_state = {{customer_state}}]]
)
SELECT COUNT(*) AS delivered_orders FROM selected_orders;
