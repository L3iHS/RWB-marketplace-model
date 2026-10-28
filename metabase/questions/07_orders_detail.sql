WITH selected_orders AS (
    SELECT * FROM mart.order_totals
    WHERE is_delivered
      [[AND purchased_at >= CAST({{date_from}} AS date)]]
      [[AND purchased_at < CAST({{date_to}} AS date) + INTERVAL '1 day']]
      [[AND customer_state = {{customer_state}}]]
)
SELECT order_id, purchased_at, customer_state, goods_amount, freight_amount,
       order_amount, units, sellers, delivery_days, delay_days,
       latest_review_score, payment_delta
FROM selected_orders ORDER BY purchased_at DESC, order_id;
