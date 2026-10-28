-- Вопрос 8. Воронка статусов.
--
-- Сколько заказов в каждом статусе, их доля и сколько из них без единой позиции.
--
-- Считаем все заказы, из mart.order_totals (одна строка = один заказ).
-- Заказ без позиций — units = 0; такие заказы остаются в модели,
-- а не теряются на соединении с позициями.
-- Контроль по разведке: 99 441 заказ, без позиций 775.

SELECT status_code                                          AS status,
       count(*)                                             AS orders,
       round(100.0 * count(*) / sum(count(*)) OVER (), 2)   AS orders_pct,
       count(*) FILTER (WHERE units = 0)                    AS orders_without_items
FROM mart.order_totals
GROUP BY status_code
ORDER BY orders DESC, status;
