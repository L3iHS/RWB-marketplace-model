-- Вопрос 6. История цены товара с наибольшим числом разных цен.
--
-- Продажи — позиции доставленных заказов (mart.delivered_items), как и в вопросах 1–5.
-- Тот же товар лидирует и по всем статусам: 31 разная цена.
-- Дата — день оформления заказа. Если в один день товар продавался по разным
-- ценам, это разные строки истории.
-- Продано единиц = число строк позиций (одна строка = одна единица).
-- При равном числе цен берём товар с большим числом проданных единиц,
-- затем по product_id — чтобы выбор был однозначным.

WITH product AS (
    SELECT product_id
    FROM mart.delivered_items
    GROUP BY product_id
    ORDER BY count(DISTINCT price) DESC, count(*) DESC, product_id
    LIMIT 1
)
SELECT d.product_id,
       d.purchased_at::date AS date,
       d.price,
       count(*)             AS units_sold
FROM mart.delivered_items d
JOIN product USING (product_id)
GROUP BY d.product_id, d.purchased_at::date, d.price
ORDER BY date, d.price;
