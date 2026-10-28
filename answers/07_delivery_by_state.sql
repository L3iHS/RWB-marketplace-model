-- Вопрос 7. Доставка по штатам покупателя (штаты, где не меньше 500 заказов).
--
-- Средний срок доставки и доля опозданий по каждому штату.
--
-- База — доставленные заказы с известной датой вручения: только по ним можно
-- посчитать срок и опоздание. Порог 500 применяется к той же базе.
-- (Если считать порог по всем заказам, набор штатов тот же — 17.)
-- Штат — сохранённый адрес этого заказа (core.order_addresses).
-- Срок доставки — календарные дни от оформления до вручения (delivery_days).
-- Опоздание — вручение позже обещанной даты (is_late).

SELECT customer_state                              AS state,
       count(*)                                    AS orders,
       round(avg(delivery_days), 2)                AS avg_delivery_days,
       round(100.0 * avg(is_late::int), 2)         AS late_pct
FROM mart.order_totals
WHERE is_delivered
  AND delivered_customer_at IS NOT NULL
GROUP BY customer_state
HAVING count(*) >= 500
ORDER BY orders DESC, state;
