-- Вопрос 5. Выручка по категориям с долей в общей выручке.
--
-- Товары без категории не выбрасываем: они идут в отдельную строку 'unknown'.
-- Для категорий без перевода показываем португальское название.
-- Оба правила заданы в core.categories.name.
-- Контроль: 74 категории, у крупнейшей 1 233 131.72, сумма = 13 221 498.11.

SELECT c.name                                                AS category,
       c.name_pt                                             AS category_pt,
       sum(d.price)                                          AS revenue,
       round(100.0 * sum(d.price) / sum(sum(d.price)) OVER (), 2) AS revenue_pct
FROM mart.delivered_items d
JOIN core.categories c USING (category_id)
GROUP BY c.category_id, c.name, c.name_pt
ORDER BY revenue DESC;
