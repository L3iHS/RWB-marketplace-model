-- Вопрос 4. Сколько у Capibara покупателей и сколько вернулись за второй покупкой.
--
-- Покупатель = человек (customer_unique_id), а не customer_id:
-- customer_id выдаётся на каждый заказ, и по нему повторных покупок не видно.
--
-- Считаем заказы всех статусов. «Вернулся за второй покупкой» — это поведение
-- покупателя: он пришёл и оформил заказ ещё раз. Если заказ потом отменил
-- продавец или товара не оказалось (canceled, unavailable), возвращение
-- покупателя всё равно состоялось. Этим вопрос отличается от выручки,
-- где важно, дошли ли деньги.
-- Для сравнения: только по доставленным заказам — 93 358 покупателей, 3.00%.
--
-- Контроль: 96 096 покупателей, вернулись 3.12%.

WITH per_customer AS (
    SELECT customer_unique_id,
           count(*) AS orders
    FROM mart.order_totals
    GROUP BY customer_unique_id
)
SELECT count(*)                                AS customers,
       count(*) FILTER (WHERE orders >= 2)     AS returned,
       round(100.0 * count(*) FILTER (WHERE orders >= 2) / count(*), 2) AS returned_pct
FROM per_customer;
