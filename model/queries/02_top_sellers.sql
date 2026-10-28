-- Считаем только позиции данного продавца, вся выгрузка.
SELECT i.seller_id, s.city, s.state, count(DISTINCT i.order_id) AS orders,
       count(*) AS units, sum(i.price) AS revenue
FROM mart.delivered_items i JOIN core.sellers s USING (seller_id)
GROUP BY i.seller_id, s.city, s.state
ORDER BY revenue DESC, i.seller_id LIMIT 10;
