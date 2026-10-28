-- Контекст текущей демонстрационной публикации.
SELECT v.version_id, v.kind, v.sequence, v.published_at,
       v.summary ->> 'orders' AS orders,
       v.summary ->> 'new_orders' AS new_orders,
       v.summary ->> 'changed_statuses' AS changed_statuses,
       v.summary ->> 'delivered_goods_amount' AS delivered_goods_amount
FROM ops.current_dataset c JOIN ops.dataset_versions v USING (version_id);

-- Синтетические операции видны отдельно от исходной истории.
SELECT status_code, count(*) AS orders, sum(goods_amount) AS goods_amount,
       count(*) FILTER (WHERE is_late) AS delivered_late
FROM mart.order_totals WHERE left(order_id, 4) = 'syn_'
GROUP BY status_code ORDER BY status_code;

SELECT purchase_month, count(DISTINCT order_id) AS delivered_orders, sum(price) AS goods_amount
FROM mart.delivered_items WHERE left(order_id, 4) = 'syn_'
GROUP BY purchase_month ORDER BY purchase_month;

SELECT order_id, status_code, purchased_at, units, lines, order_amount,
       paid_amount, payment_delta, delivery_days, is_late
FROM mart.order_totals WHERE left(order_id, 4) = 'syn_'
ORDER BY purchased_at DESC, order_id LIMIT 15;
