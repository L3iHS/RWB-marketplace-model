-- Все статусы: повторное оформление, совпадающее с контрольным ответом.
WITH purchases AS (
    SELECT p.customer_unique_id, count(DISTINCT o.order_id) AS orders
    FROM core.orders o JOIN core.customer_order_profiles p USING (customer_id)
    GROUP BY p.customer_unique_id
)
SELECT count(*) AS customers, count(*) FILTER (WHERE orders >= 2) AS repeat_customers,
       round(100.0 * count(*) FILTER (WHERE orders >= 2) / nullif(count(*), 0), 2) AS repeat_percent
FROM purchases;
