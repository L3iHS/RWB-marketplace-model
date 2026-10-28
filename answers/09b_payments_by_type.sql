-- Вопрос 9, часть 2. Способы оплаты целиком: за весь период и по всем штатам.
--
-- Платёж — запись core.order_payments, заказы всех статусов.
-- Средний срок рассрочки — среднее installments по платежам этого способа.

SELECT payment_type,
       count(*)                      AS payments,
       round(avg(installments), 2)   AS avg_installments
FROM core.order_payments
GROUP BY payment_type
ORDER BY payments DESC, payment_type;
