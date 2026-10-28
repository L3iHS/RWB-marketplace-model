-- Каждый дочерний факт агрегируется отдельно до уровня заказа. JOIN не размножает суммы.
CREATE VIEW mart.order_summary AS
WITH items AS (
    SELECT order_id,count(*) AS item_rows,count(*) AS units,
           sum(price) AS goods_total,sum(freight_value) AS freight_total,
           count(DISTINCT seller_id) AS seller_count
    FROM core.order_items GROUP BY order_id
), payments AS (
    SELECT order_id,count(*) AS payment_count,sum(payment_value) AS paid_total
    FROM core.order_payments GROUP BY order_id
), review_counts AS (
    SELECT order_id,count(*) AS review_count FROM core.order_reviews GROUP BY order_id
), latest_review AS (
    SELECT DISTINCT ON(order_id) order_id,score AS latest_review_score
    FROM core.order_reviews ORDER BY order_id,answered_at DESC NULLS LAST,created_at DESC NULLS LAST,review_id
)
SELECT o.*,c.buyer_id,c.city AS customer_city,c.state AS customer_state,
       coalesce(i.item_rows,0) AS item_rows,coalesce(i.units,0) AS units,
       coalesce(i.seller_count,0) AS seller_count,i.goods_total,i.freight_total,
       i.goods_total+i.freight_total AS order_total,
       coalesce(p.payment_count,0) AS payment_count,p.paid_total,
       p.paid_total-i.goods_total-i.freight_total AS payment_delta,
       coalesce(rc.review_count,0) AS review_count,r.latest_review_score,
       o.delivered_customer_at::date-o.estimated_delivery_at::date AS delay_days,
       o.delivered_customer_at-o.purchased_at AS delivery_duration
FROM core.orders o
JOIN core.customer_profiles c USING(customer_id)
LEFT JOIN items i USING(order_id)
LEFT JOIN payments p USING(order_id)
LEFT JOIN review_counts rc USING(order_id)
LEFT JOIN latest_review r USING(order_id);
COMMENT ON VIEW mart.order_summary IS 'Одна строка на заказ. Отсутствующие денежные факты — NULL, а не фиктивный ноль. Последний отзыв выбран детерминированно.';
CREATE VIEW mart.sales_items AS
SELECT i.*,o.purchased_at,c.buyer_id,p.category_key
FROM core.order_items i JOIN core.orders o USING(order_id)
JOIN core.customer_profiles c USING(customer_id) JOIN core.products p USING(product_id)
WHERE o.order_status='delivered';
CREATE VIEW mart.seller_sales AS
SELECT s.seller_id,s.city,s.state,count(DISTINCT i.order_id) AS order_count,
       count(*) AS units,sum(i.price) AS revenue
FROM mart.sales_items i JOIN core.sellers s USING(seller_id)
GROUP BY s.seller_id,s.city,s.state;
CREATE VIEW mart.category_sales AS
WITH totals AS (
    SELECT category_key,sum(price) AS revenue FROM mart.sales_items GROUP BY category_key
)
SELECT c.category_key,c.name_pt,c.name_en,c.is_unknown,
       coalesce(c.name_en,c.name_pt,'Без категории') AS category,
       t.revenue,100*t.revenue/nullif(sum(t.revenue) OVER(),0) AS share_pct
FROM totals t JOIN core.categories c USING(category_key);
CREATE VIEW mart.buyer_activity AS
SELECT b.buyer_id,count(o.order_id) AS order_count,
       count(o.order_id) FILTER(WHERE o.order_status='delivered') AS delivered_order_count,
       min(o.purchased_at) AS first_order_at,max(o.purchased_at) AS last_order_at
FROM core.buyers b LEFT JOIN core.customer_profiles c USING(buyer_id)
LEFT JOIN core.orders o USING(customer_id) GROUP BY b.buyer_id;
CREATE FUNCTION mart.sales_by_month(start_month date,end_month date)
RETURNS TABLE(month date,order_count bigint,revenue numeric)
LANGUAGE sql STABLE AS $$
    WITH sales AS (
        SELECT date_trunc('month',purchased_at)::date AS month,count(*) AS order_count,sum(goods_total) AS revenue
        FROM mart.order_summary WHERE order_status='delivered'
        AND purchased_at>=date_trunc('month',start_month::timestamp)
        AND purchased_at<date_trunc('month',end_month::timestamp)+interval '1 month'
        GROUP BY 1
    )
    SELECT calendar.month::date,coalesce(s.order_count,0),coalesce(s.revenue,0)
    FROM generate_series(date_trunc('month',start_month::timestamp),date_trunc('month',end_month::timestamp),interval '1 month') calendar(month)
    LEFT JOIN sales s ON s.month=calendar.month::date ORDER BY 1
$$;
CREATE VIEW mart.quality_issues AS
SELECT 'warning'::text AS severity,'missing_category'::text AS issue_code,'product'::text AS entity_type,
       product_id AS entity_id,'Категория отсутствует в источнике'::text AS detail
FROM core.products WHERE category_key='__unknown__'
UNION ALL SELECT 'warning','missing_translation','category',category_key,'Сохранено португальское название'
FROM core.categories WHERE NOT is_unknown AND name_en IS NULL
UNION ALL SELECT 'warning','delivered_without_date','order',order_id,'Доставлен по статусу, дата вручения отсутствует'
FROM core.orders WHERE order_status='delivered' AND delivered_customer_at IS NULL
UNION ALL SELECT 'warning','carrier_before_approval','order',order_id,'Передача в доставку раньше подтверждения оплаты'
FROM core.orders WHERE delivered_carrier_at<approved_at
UNION ALL SELECT 'warning','delivery_before_purchase','order',order_id,'Вручение раньше оформления'
FROM core.orders WHERE delivered_customer_at<purchased_at
UNION ALL SELECT 'warning','payment_mismatch','order',order_id,'Платежи минус товары и доставка: '||payment_delta::text
FROM mart.order_summary WHERE abs(payment_delta)>0.01
UNION ALL SELECT 'warning','missing_payment','order',order_id,'Записи платежа нет; сумма не заменена нулём'
FROM mart.order_summary WHERE payment_count=0
UNION ALL SELECT CASE WHEN order_status='delivered' THEN 'error' ELSE 'info' END,'missing_items','order',order_id,'Нет позиций; статус: '||order_status
FROM mart.order_summary WHERE item_rows=0
UNION ALL SELECT 'info','multiple_reviews','order',order_id,'Число записей отзыва: '||review_count::text
FROM mart.order_summary WHERE review_count>1;
