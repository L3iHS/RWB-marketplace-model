-- Вопрос 3. Средний чек заказа.
--
-- Чек — свойство заказа целиком: товары + доставка (order_amount),
-- сначала сумма по заказу, потом среднее по заказам (mart.order_totals).
-- Берём доставленные заказы, как и для выручки.
-- Строка чека = товар одного продавца в заказе (lines),
-- единица = одна строка order_items (units).
-- Контроль: 159.88. Ответы 123.75 и 139.97 означают расчёт на уровне позиции.

SELECT round(avg(order_amount), 2) AS average_check,
       round(avg(lines), 4)        AS average_lines,
       round(avg(units), 4)        AS average_units
FROM mart.order_totals
WHERE is_delivered;
