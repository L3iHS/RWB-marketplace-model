-- Вопрос 1. Выручка и число заказов по месяцам, сентябрь 2016 — август 2018.
--
-- Выручка = сумма price доставленных заказов, без доставки (mart.delivered_items).
-- Заказы = число доставленных заказов, чтобы считать оба показателя по одному правилу.
-- Месяц = месяц оформления заказа.
-- Отчёт строим от календаря: ноябрь 2016 без заказов показывается с нулём.
-- Контроль: 24 строки, одна с нулевой выручкой, итого 13 221 498.11.

WITH months AS (
    SELECT DISTINCT month
    FROM core.calendar
    WHERE month BETWEEN '2016-09-01' AND '2018-08-01'
), revenue AS (
    SELECT purchase_month,
           count(DISTINCT order_id) AS orders,
           sum(price)               AS revenue
    FROM mart.delivered_items
    GROUP BY purchase_month
)
SELECT to_char(m.month, 'YYYY-MM')  AS month,
       coalesce(r.orders, 0)        AS orders,
       coalesce(r.revenue, 0)       AS revenue
FROM months m
LEFT JOIN revenue r ON r.purchase_month = m.month
ORDER BY m.month;
