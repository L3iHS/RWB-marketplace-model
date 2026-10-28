-- Вопрос 10. Связь оценки покупателя со сроком доставки.
--
-- Для каждой оценки от 1 до 5 — средний срок доставки и доля опозданий.
--
-- База — доставленные заказы с известной датой вручения и с отзывом.
-- Оценка заказа — последний отзыв (latest_review_score): у 547 заказов
-- несколько отзывов, и заказ должен попасть ровно в одну строку.
-- Срок и опоздание считаются так же, как в вопросе 7.
-- Оценки берём из справочника 1–5, чтобы оценка без заказов не пропала.

SELECT s.score,
       count(o.order_id)                       AS orders,
       round(avg(o.delivery_days), 2)          AS avg_delivery_days,
       round(100.0 * avg(o.is_late::int), 2)   AS late_pct
FROM generate_series(1, 5) AS s(score)
LEFT JOIN mart.order_totals o
       ON o.latest_review_score = s.score
      AND o.is_delivered
      AND o.delivered_customer_at IS NOT NULL
GROUP BY s.score
ORDER BY s.score;
