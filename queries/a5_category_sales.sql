-- A5: ключ категории сохраняет различия при отсутствии перевода. Округляем только вывод.
SELECT category_key,category,revenue,round(share_pct,4) AS share_pct
FROM mart.category_sales ORDER BY revenue DESC,category_key;
