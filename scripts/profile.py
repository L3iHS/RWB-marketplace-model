"""Воспроизводимый read-only профиль raw; результат в artifacts/profile.json."""
import hashlib
import json
from pathlib import Path
from db import connect

ROOT = Path(__file__).resolve().parent.parent
QUERIES = {
    'counts': """SELECT 'orders' AS entity, count(*) AS rows FROM raw.orders
        UNION ALL SELECT 'order_items', count(*) FROM raw.order_items
        UNION ALL SELECT 'order_payments', count(*) FROM raw.order_payments
        UNION ALL SELECT 'order_reviews', count(*) FROM raw.order_reviews
        UNION ALL SELECT 'products', count(*) FROM raw.products
        UNION ALL SELECT 'customers', count(*) FROM raw.customers
        UNION ALL SELECT 'sellers', count(*) FROM raw.sellers
        UNION ALL SELECT 'product_category_translation', count(*) FROM raw.product_category_translation
        ORDER BY entity""",
    'statuses': 'SELECT order_status, count(*) FROM raw.orders GROUP BY 1 ORDER BY 1',
    'keys': """SELECT 'order_id' AS key, count(*)-count(DISTINCT order_id) AS duplicates FROM raw.orders
        UNION ALL SELECT 'customer_id',count(*)-count(DISTINCT customer_id) FROM raw.customers
        UNION ALL SELECT 'person_id',count(DISTINCT customer_unique_id) FROM raw.customers
        UNION ALL SELECT 'order_item',count(*)-count(DISTINCT (order_id,order_item_id)) FROM raw.order_items
        UNION ALL SELECT 'payment',count(*)-count(DISTINCT (order_id,payment_sequential)) FROM raw.order_payments
        UNION ALL SELECT 'review_id',count(*)-count(DISTINCT review_id) FROM raw.order_reviews
        UNION ALL SELECT 'review_order_pair',count(*)-count(DISTINCT (review_id,order_id)) FROM raw.order_reviews""",
    'missing': """SELECT count(*) FILTER (WHERE order_approved_at IS NULL) AS approval,
        count(*) FILTER (WHERE order_delivered_carrier_date IS NULL) AS carrier,
        count(*) FILTER (WHERE order_delivered_customer_date IS NULL) AS delivered,
        count(*) FILTER (WHERE order_status='delivered' AND order_delivered_customer_date IS NULL) AS delivered_without_date
        FROM raw.orders""",
    'categories': """SELECT count(DISTINCT p.product_category_name) AS names,
        count(*) FILTER(WHERE p.product_category_name IS NULL) AS products_missing,
        count(*) FILTER(WHERE p.product_category_name IS NOT NULL AND t.product_category_name IS NULL) AS products_untranslated,
        array_agg(DISTINCT p.product_category_name) FILTER(WHERE p.product_category_name IS NOT NULL AND t.product_category_name IS NULL) AS untranslated
        FROM raw.products p LEFT JOIN raw.product_category_translation t USING(product_category_name)""",
    'order_totals': """WITH i AS (SELECT order_id,count(*) n,sum(price::numeric) goods,sum(freight_value::numeric) freight FROM raw.order_items GROUP BY 1),
        p AS (SELECT order_id,sum(payment_value::numeric) paid FROM raw.order_payments GROUP BY 1)
        SELECT o.order_status,count(*) orders,count(i.order_id) orders_with_items,
        sum(goods) goods,sum(freight) freight,sum(paid) payments,avg(goods+freight) avg_basket,
        avg(n) avg_units,count(*) FILTER(WHERE abs(goods+freight-paid)>0.01) mismatches
        FROM raw.orders o LEFT JOIN i USING(order_id) LEFT JOIN p USING(order_id) GROUP BY 1 ORDER BY 1""",
    'orphans': """SELECT 'orders_customer' AS relation,count(*) FROM raw.orders o LEFT JOIN raw.customers c USING(customer_id) WHERE c.customer_id IS NULL
        UNION ALL SELECT 'item_order',count(*) FROM raw.order_items i LEFT JOIN raw.orders o USING(order_id) WHERE o.order_id IS NULL
        UNION ALL SELECT 'item_product',count(*) FROM raw.order_items i LEFT JOIN raw.products p USING(product_id) WHERE p.product_id IS NULL
        UNION ALL SELECT 'item_seller',count(*) FROM raw.order_items i LEFT JOIN raw.sellers s USING(seller_id) WHERE s.seller_id IS NULL
        UNION ALL SELECT 'payment_order',count(*) FROM raw.order_payments p LEFT JOIN raw.orders o USING(order_id) WHERE o.order_id IS NULL
        UNION ALL SELECT 'review_order',count(*) FROM raw.order_reviews r LEFT JOIN raw.orders o USING(order_id) WHERE o.order_id IS NULL""",
    'repeats': """WITH people AS(SELECT customer_unique_id,count(*) AS orders FROM raw.customers GROUP BY 1)
        SELECT count(*) people,count(*) FILTER(WHERE orders>1) returning_buyers,
        100.0*count(*) FILTER(WHERE orders>1)/count(*) pct FROM people""",
    'reviews_per_order': """SELECT n,count(*) orders FROM (SELECT order_id,count(*) n FROM raw.order_reviews GROUP BY 1) s GROUP BY 1 ORDER BY 1""",
    'chronology': """SELECT count(*) FILTER(WHERE order_approved_at::timestamp < order_purchase_timestamp::timestamp) AS approval_before_purchase,
        count(*) FILTER(WHERE order_delivered_customer_date::timestamp < order_purchase_timestamp::timestamp) AS delivery_before_purchase,
        count(*) FILTER(WHERE order_delivered_carrier_date::timestamp < order_approved_at::timestamp) AS carrier_before_approval FROM raw.orders""",
}

def main():
    report = {}
    with connect() as conn, conn.cursor() as cur:
        cur.execute('SET TRANSACTION READ ONLY')
        for name, sql in QUERIES.items():
            cur.execute(sql)
            columns = [c.name for c in cur.description]
            report[name] = [dict(zip(columns, row)) for row in cur.fetchall()]
    report['files'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'data').glob('*.csv'))}
    (ROOT/'artifacts').mkdir(exist_ok=True)
    (ROOT/'artifacts/profile.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2,default=str))

if __name__ == '__main__':
    main()
