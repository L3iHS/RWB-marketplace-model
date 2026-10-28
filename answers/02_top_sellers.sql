-- Вопрос 2. Топ-10 продавцов по выручке, с городом и штатом.
--
-- Выручку продавца считаем по его позициям (mart.delivered_items), а не по сумме
-- заказа: в одном заказе бывают товары разных продавцов.
-- Единиц товара = число строк позиций (одна строка = одна единица).
-- Контроль: у первого продавца 226 987.93.

SELECT d.seller_id,
       s.city,
       s.state,
       count(DISTINCT d.order_id) AS orders,
       count(*)                   AS units,
       sum(d.price)               AS revenue
FROM mart.delivered_items d
JOIN core.sellers s USING (seller_id)
GROUP BY d.seller_id, s.city, s.state
ORDER BY revenue DESC, d.seller_id
LIMIT 10;
