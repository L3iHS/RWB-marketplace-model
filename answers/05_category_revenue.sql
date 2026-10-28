-- Вопрос 5. Выручка по категориям с долей в общей выручке.
--
-- Товары без категории не выбрасываем: они идут в отдельную строку '__unknown__'.
-- Для категорий без перевода показываем португальское название.
-- Оба правила заданы в core.categories.
-- Контроль: 74 категории, у крупнейшей 1 233 131.72, сумма = 13 221 498.11.

SELECT name                   AS category,
       category_key,
       revenue,
       round(revenue_pct, 2)  AS revenue_pct
FROM mart.category_sales
ORDER BY revenue DESC, category_key;
