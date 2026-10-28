#!/usr/bin/env python3
"""Read-only профилирование raw. Запуск: .venv/bin/python scripts/profile_raw.py.
Результат: data/profile_raw.json; не создаёт и не меняет таблицы.
"""
import argparse
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import sql
from load_raw import MAPPING

QUERIES = {
    "statuses": "SELECT order_status, count(*) AS orders FROM raw.orders GROUP BY 1 ORDER BY 2 DESC",
    "period": "SELECT min(order_purchase_timestamp) AS first_purchase, max(order_purchase_timestamp) AS last_purchase FROM raw.orders",
    "customers": """SELECT count(*) AS records, count(DISTINCT customer_id) AS customer_ids,
        count(DISTINCT customer_unique_id) AS people FROM raw.customers""",
    "repeat_customers": """WITH counts AS (SELECT c.customer_unique_id, count(*) AS orders
        FROM raw.orders o JOIN raw.customers c USING(customer_id) GROUP BY 1)
        SELECT count(*) AS people, count(*) FILTER (WHERE orders > 1) AS repeat_people,
        round(100.0 * count(*) FILTER (WHERE orders > 1) / count(*), 4) AS repeat_pct FROM counts""",
    "multiplicity": """SELECT 'items' AS entity, count(*) AS orders, max(n) AS max_per_order FROM
        (SELECT order_id, count(*) n FROM raw.order_items GROUP BY 1) t
        UNION ALL SELECT 'payments', count(*), max(n) FROM
        (SELECT order_id, count(*) n FROM raw.order_payments GROUP BY 1) t
        UNION ALL SELECT 'reviews', count(*), max(n) FROM
        (SELECT order_id, count(*) n FROM raw.order_reviews GROUP BY 1) t""",
    "multiple_children": """SELECT 'multiple_payments' AS metric, count(*) AS orders FROM
        (SELECT order_id FROM raw.order_payments GROUP BY 1 HAVING count(*) > 1) t
        UNION ALL SELECT 'multiple_reviews', count(*) FROM
        (SELECT order_id FROM raw.order_reviews GROUP BY 1 HAVING count(*) > 1) t
        UNION ALL SELECT 'multiple_sellers', count(*) FROM
        (SELECT order_id FROM raw.order_items GROUP BY 1 HAVING count(DISTINCT seller_id)>1) t""",
    "review_keys": """SELECT count(*) AS rows, count(DISTINCT review_id) AS review_ids,
        count(DISTINCT (review_id, order_id)) AS review_order_pairs FROM raw.order_reviews""",
    "category_gaps": """SELECT p.product_category_name, count(*) AS products
        FROM raw.products p LEFT JOIN raw.product_category_translation t USING(product_category_name)
        WHERE t.product_category_name IS NULL GROUP BY 1 ORDER BY 2 DESC""",
    "payment_types": """SELECT payment_type, count(*) AS records,
        min(payment_installments::integer) AS min_installments,
        max(payment_installments::integer) AS max_installments,
        sum(payment_value::numeric) AS amount FROM raw.order_payments GROUP BY 1 ORDER BY 2 DESC""",
    "review_scores": "SELECT review_score, count(*) AS records FROM raw.order_reviews GROUP BY 1 ORDER BY 1",
    "status_amounts": """SELECT o.order_status, count(*) AS units, count(DISTINCT o.order_id) AS orders,
        sum(i.price::numeric) AS goods, sum(i.freight_value::numeric) AS freight,
        sum(i.price::numeric+i.freight_value::numeric) AS total
        FROM raw.orders o JOIN raw.order_items i USING(order_id) GROUP BY 1 ORDER BY 1""",
    "delivery_dates": """SELECT order_status, count(*) AS orders,
        count(*) FILTER (WHERE nullif(order_approved_at,'') IS NULL) AS missing_approved,
        count(*) FILTER (WHERE nullif(order_delivered_carrier_date,'') IS NULL) AS missing_carrier,
        count(*) FILTER (WHERE nullif(order_delivered_customer_date,'') IS NULL) AS missing_delivered,
        count(*) FILTER (WHERE order_approved_at::timestamp < order_purchase_timestamp::timestamp) AS approved_before_purchase,
        count(*) FILTER (WHERE order_delivered_customer_date::timestamp < order_delivered_carrier_date::timestamp) AS delivered_before_carrier
        FROM raw.orders GROUP BY 1 ORDER BY 1""",
    "amount_reconciliation": """WITH i AS (SELECT order_id, sum(price::numeric+freight_value::numeric) amount
        FROM raw.order_items GROUP BY 1), p AS (SELECT order_id, sum(payment_value::numeric) amount
        FROM raw.order_payments GROUP BY 1)
        SELECT count(*) AS orders_with_both, count(*) FILTER (WHERE i.amount <> p.amount) AS different_exact,
        count(*) FILTER (WHERE abs(i.amount-p.amount)>0.01) AS different_over_cent,
        max(abs(i.amount-p.amount)) AS max_absolute_difference
        FROM i JOIN p USING(order_id)""",
    "monthly_delivered": """WITH months AS (
        SELECT generate_series('2016-09-01'::date, '2018-08-01'::date, interval '1 month') AS month),
        amounts AS (SELECT o.order_id, date_trunc('month', o.order_purchase_timestamp::timestamp) AS month,
        sum(i.price::numeric) AS goods, sum(i.price::numeric+i.freight_value::numeric) AS total
        FROM raw.orders o JOIN raw.order_items i USING(order_id)
        WHERE o.order_status='delivered' GROUP BY 1,2)
        SELECT m.month::date, count(a.order_id) AS orders, coalesce(sum(a.goods),0) AS goods,
        coalesce(sum(a.total),0) AS total FROM months m LEFT JOIN amounts a USING(month) GROUP BY 1 ORDER BY 1""",
    "delivered_order_averages": """WITH amounts AS (SELECT o.order_id, count(*) AS units,
        count(DISTINCT (i.product_id,i.seller_id)) AS product_seller_lines,
        sum(i.price::numeric+i.freight_value::numeric) AS total
        FROM raw.orders o JOIN raw.order_items i USING(order_id)
        WHERE o.order_status='delivered' GROUP BY 1)
        SELECT count(*) AS orders, round(avg(total),2) AS avg_check,
        round(avg(units),4) AS avg_units, round(avg(product_seller_lines),4) AS avg_product_seller_lines FROM amounts""",
}
KEYS = {
    "orders": ["order_id"], "order_items": ["order_id", "order_item_id"],
    "order_payments": ["order_id", "payment_sequential"], "order_reviews": ["review_id", "order_id"],
    "products": ["product_id"], "sellers": ["seller_id"], "customers": ["customer_id"],
    "product_category_translation": ["product_category_name"],
}
LINKS = [
    ("orders", "customer_id", "customers", "customer_id"),
    ("order_items", "order_id", "orders", "order_id"),
    ("order_items", "product_id", "products", "product_id"),
    ("order_items", "seller_id", "sellers", "seller_id"),
    ("order_payments", "order_id", "orders", "order_id"),
    ("order_reviews", "order_id", "orders", "order_id"),
    ("orders", "order_id", "order_items", "order_id"),
    ("orders", "order_id", "order_payments", "order_id"),
    ("orders", "order_id", "order_reviews", "order_id"),
]


def encode(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn', default='postgresql://hack:hack@localhost:5432/marketplace')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent.parent / 'data/profile_raw.json')
    args = parser.parse_args()
    report = {}
    with psycopg2.connect(args.dsn) as conn:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            report['tables'] = {}
            for _, table, columns in MAPPING:
                name = table.split('.')[1]
                ident = sql.Identifier('raw', name)
                cur.execute(sql.SQL('SELECT count(*) AS rows FROM {}').format(ident))
                profile = dict(cur.fetchone())
                key = sql.SQL(', ').join(map(sql.Identifier, KEYS[name]))
                cur.execute(sql.SQL('SELECT count(*) AS duplicate_groups, coalesce(sum(n-1),0) AS extra_rows FROM (SELECT count(*) n FROM {} GROUP BY {} HAVING count(*)>1) t').format(ident,key))
                profile['candidate_key'] = KEYS[name]
                profile['key_duplicates'] = dict(cur.fetchone())
                expressions = [sql.SQL("count(*) FILTER (WHERE nullif(btrim({}), '') IS NULL) AS {}").format(sql.Identifier(c),sql.Identifier(c)) for c in columns]
                cur.execute(sql.SQL('SELECT {} FROM {}').format(sql.SQL(', ').join(expressions),ident))
                profile['missing_values'] = dict(cur.fetchone())
                types = {}
                for column in columns:
                    if column.endswith(('_timestamp', '_date', '_at')):
                        types[column] = 'timestamp'
                    elif column in {'price', 'freight_value', 'payment_value'}:
                        types[column] = 'numeric'
                    elif column in {'order_item_id', 'payment_sequential', 'payment_installments', 'review_score'} or column in {'product_name_lenght', 'product_description_lenght', 'product_photos_qty', 'product_weight_g', 'product_length_cm', 'product_height_cm', 'product_width_cm'}:
                        types[column] = 'integer'
                profile['invalid_types'] = {}
                for column, target in types.items():
                    cur.execute(sql.SQL("SELECT count(*) AS invalid FROM {} WHERE nullif(btrim({}), '') IS NOT NULL AND NOT pg_input_is_valid({}, %s)").format(ident, sql.Identifier(column), sql.Identifier(column)), (target,))
                    profile['invalid_types'][column] = {'target': target, 'invalid': cur.fetchone()['invalid']}
                report['tables'][name] = profile
            report['unmatched_links'] = {}
            for child, ck, parent, pk in LINKS:
                cur.execute(sql.SQL('SELECT count(*) AS unmatched FROM raw.{} c WHERE NOT EXISTS (SELECT 1 FROM raw.{} p WHERE c.{}=p.{})').format(*map(sql.Identifier,[child,parent,ck,pk])))
                report['unmatched_links'][f'{child}.{ck} -> {parent}.{pk}'] = cur.fetchone()['unmatched']
            for name, query in QUERIES.items():
                cur.execute(query)
                report[name] = [dict(row) for row in cur.fetchall()]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=encode)+'\n',encoding='utf-8')
    print(f'Профиль записан: {args.output}')
    print('Всего исходных строк:', sum(p['rows'] for p in report['tables'].values()))
    for section in ['customers','repeat_customers','review_keys','multiple_children','category_gaps','amount_reconciliation','delivered_order_averages']:
        print(section, json.dumps(report[section],ensure_ascii=False,default=encode))


if __name__ == '__main__':
    main()
