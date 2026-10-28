-- A2: только позиции конкретного продавца, уникальные заказы внутри продавца.
SELECT seller_id,city,state,order_count,units,revenue
FROM mart.seller_sales ORDER BY revenue DESC,seller_id LIMIT 10;
