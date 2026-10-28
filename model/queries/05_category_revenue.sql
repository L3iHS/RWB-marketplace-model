-- Исходное название — устойчивый ключ группировки, перевод — атрибут.
WITH amounts AS (
    SELECT category_id, sum(price) AS revenue FROM mart.delivered_items GROUP BY category_id
)
SELECT c.name_pt AS category_pt,
       coalesce(c.name_en, c.name_pt, 'Категория не указана') AS category,
       a.revenue, round(100.0 * a.revenue / nullif(sum(a.revenue) OVER (), 0), 4) AS revenue_percent
FROM amounts a JOIN core.categories c USING(category_id)
ORDER BY a.revenue DESC, c.name_pt NULLS LAST;
