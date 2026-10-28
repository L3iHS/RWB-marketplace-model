-- Вопрос 9, часть 1. Способы оплаты и рассрочка по штатам покупателя за 2018 год.
--
-- Платёж — запись core.order_payments (у заказа их может быть несколько).
-- 2018 год — по дате оформления заказа. Считаем платежи заказов всех статусов:
-- вопрос о том, как покупатели платят, а не о выручке.
-- Штат — адрес покупателя в этом заказе.
-- Средний срок рассрочки — среднее installments по платежам. Для всех способов,
-- кроме кредитной карты, это обычно 1. Исходные 0 сохраняются и участвуют
-- в среднем; они отдельно отмечены в реестре качества.

SELECT o.customer_state                AS state,
       count(*)                        AS payments,
       sum(p.payment_value)            AS amount,
       round(avg(p.installments), 2)   AS avg_installments
FROM core.order_payments p
JOIN mart.order_totals o USING (order_id)
WHERE o.purchased_at >= '2018-01-01'
  AND o.purchased_at <  '2019-01-01'
GROUP BY o.customer_state
ORDER BY payments DESC, state;
