"""Интеграционные тесты модели на PostgreSQL 16.

DatasetContract — на настоящей выгрузке в базе marketplace:
контрольные цифры, повторная сборка, ответы не читают raw.

EdgeCases — на крошечном искусственном наборе в отдельной временной базе:
каждый тест проверяет одно правило модели на случае, где ответ известен заранее.
Временная база удаляется после тестов.

Запуск: docker compose run --rm app test
"""
import hashlib
import os
import subprocess
import sys
import unittest
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from psycopg2 import sql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from db import connect  # noqa: E402


def build(dbname, *files, success=True):
    """Запускает run.py в указанной базе: без файлов — полную сборку модели."""
    env = dict(os.environ, PGDATABASE=dbname)
    command = ['sql', *files] if files else ['build']
    result = subprocess.run([sys.executable, 'run.py', *command], cwd=ROOT, env=env,
                            capture_output=True, text=True, encoding='utf-8')
    if success and result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result


def rows(dbname, query):
    with connect(dbname) as conn, conn.cursor() as cur:
        cur.execute(query)
        return cur.fetchall()


def fingerprint(dbname, schema):
    """Отпечаток содержимого всех таблиц схемы: меняется при любом изменении данных."""
    with connect(dbname) as conn, conn.cursor() as cur:
        cur.execute('SELECT tablename FROM pg_tables WHERE schemaname = %s ORDER BY tablename', (schema,))
        tables = [row[0] for row in cur.fetchall()]
        digest = hashlib.sha256()
        for table in tables:
            cur.execute(sql.SQL(
                "SELECT count(*), md5(string_agg(row_hash, '' ORDER BY row_hash)) "
                "FROM (SELECT md5(to_jsonb(t)::text) AS row_hash FROM {}.{} t) s"
            ).format(sql.Identifier(schema), sql.Identifier(table)))
            digest.update(str((table, cur.fetchone())).encode())
        return digest.hexdigest()


class DatasetContract(unittest.TestCase):
    """Настоящая выгрузка организаторов."""

    def test_control_numbers(self):
        build('marketplace', 'answers/99_controls.sql')

    def test_rebuild_preserves_raw_and_model(self):
        before_raw = fingerprint('marketplace', 'raw')
        before_core = fingerprint('marketplace', 'core')
        build('marketplace')
        self.assertEqual(before_raw, fingerprint('marketplace', 'raw'))
        self.assertEqual(before_core, fingerprint('marketplace', 'core'))

    def test_answers_do_not_read_raw(self):
        for path in (ROOT / 'answers').glob('*.sql'):
            with self.subTest(path=path.name):
                self.assertNotRegex(path.read_text(), r'\braw\.')


class EdgeCases(unittest.TestCase):
    """Искусственный набор: 3 покупателя, 4 заказа, 6 позиций, 4 платежа, 3 отзыва.

    b1 — один человек с двумя адресами (c1, c2) и двумя заказами (o1, o2).
    o1 — три единицы товара от двух продавцов, два платежа, два отзыва.
    o2 — товар без категории, доставлен на день позже обещанного.
    o3 — отменён: в выручку не входит.
    o4 — доставлен, но без даты вручения и без платежа; товар без перевода категории.
    Февраль 2017 — месяц без заказов.
    """

    @classmethod
    def setUpClass(cls):
        cls.dbname = 'rwb_test_' + uuid.uuid4().hex[:12]
        admin = connect('postgres')
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.dbname)))
        admin.close()
        cls.addClassCleanup(cls.drop_database)
        with connect(cls.dbname) as conn, conn.cursor() as cur:
            cur.execute('CREATE SCHEMA raw')
            cur.execute((ROOT / 'scripts/init/02_raw_ddl.sql').read_text())
            cur.execute("""
                INSERT INTO raw.customers(customer_id, customer_unique_id, customer_zip_code_prefix, customer_city, customer_state) VALUES
                ('c1','b1','00123','first','SP'), ('c2','b1','00456','second','RJ'),
                ('c3','b2','00123','third','SP'), ('c4','b3','00567','fourth','SP');
                INSERT INTO raw.sellers(seller_id, seller_city, seller_state) VALUES
                ('s1','city1','SP'), ('s2','city2','RJ');
                INSERT INTO raw.product_category_translation VALUES ('known','Known',NULL,now());
                INSERT INTO raw.products(product_id, product_category_name) VALUES
                ('p1','known'), ('p2','known'), ('p3',NULL), ('p4','untranslated');
                INSERT INTO raw.orders(order_id, customer_id, order_status, order_purchase_timestamp,
                                       order_delivered_customer_date, order_estimated_delivery_date) VALUES
                ('o1','c1','delivered','2017-01-15 10:00','2017-01-20 17:00','2017-01-20'),
                ('o2','c2','delivered','2017-03-01 10:00','2017-03-05 12:00','2017-03-04'),
                ('o3','c3','canceled', '2017-03-01 12:00',NULL,NULL),
                ('o4','c4','delivered','2017-03-02 10:00',NULL,NULL);
                INSERT INTO raw.order_items(order_id, order_item_id, product_id, seller_id, price, freight_value) VALUES
                ('o1','1','p1','s1','10.00','1.00'), ('o1','2','p1','s1','10.00','1.00'),
                ('o1','3','p2','s2','20.00','2.00'), ('o2','1','p3','s1','30.00','3.00'),
                ('o3','1','p1','s1','100.00','10.00'), ('o4','1','p4','s1','5.00','0.00');
                INSERT INTO raw.order_payments(order_id, payment_sequential, payment_type, payment_installments, payment_value) VALUES
                ('o1','1','credit_card','4','40.00'), ('o1','2','voucher','1','4.00'),
                ('o2','1','credit_card','1','33.00'), ('o3','1','credit_card','1','110.00');
                INSERT INTO raw.order_reviews(review_id, order_id, review_score, review_creation_date, review_answer_timestamp) VALUES
                ('r1','o1','1','2017-01-21','2017-01-22'), ('r2','o1','5','2017-01-23','2017-01-24'),
                ('r1','o2','3','2017-03-06','2017-03-07');
            """)
        build(cls.dbname)

    @classmethod
    def drop_database(cls):
        if not cls.dbname.startswith('rwb_test_'):
            raise AssertionError('Небезопасное имя тестовой базы')
        admin = connect('postgres')
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(cls.dbname)))
        admin.close()

    def query(self, query):
        return rows(self.dbname, query)

    def test_children_do_not_inflate_totals(self):
        # 3 позиции × 2 платежа × 2 отзыва при прямом JOIN дали бы 12 строк.
        self.assertEqual(
            self.query("SELECT units, lines, goods_amount, freight_amount, paid_amount, review_count "
                       "FROM mart.order_totals WHERE order_id = 'o1'"),
            [(3, 2, Decimal('40'), Decimal('4'), Decimal('44'), 2)])

    def test_installments_do_not_multiply_payment(self):
        self.assertEqual(self.query("SELECT sum(payment_value) FROM core.order_payments WHERE order_id = 'o1'"),
                         [(Decimal('44'),)])

    def test_seller_gets_only_own_items(self):
        self.assertEqual(self.query('SELECT seller_id, orders, units, revenue FROM mart.seller_sales ORDER BY seller_id'),
                         [('s1', 3, 4, Decimal('55')), ('s2', 1, 1, Decimal('20'))])

    def test_missing_category_and_translation_preserved(self):
        self.assertEqual(self.query('SELECT category_key, name, revenue FROM mart.category_sales ORDER BY category_key'),
                         [('__unknown__', 'unknown', Decimal('30')),
                          ('known', 'Known', Decimal('40')),
                          ('untranslated', 'untranslated', Decimal('5'))])

    def test_average_check_at_order_level(self):
        # Чеки доставленных заказов: 44, 33, 5 → 27.33. По позициям вышло бы иначе.
        self.assertEqual(self.query('SELECT round(avg(order_amount), 2) FROM mart.order_totals WHERE is_delivered'),
                         [(Decimal('27.33'),)])

    def test_person_not_order_profile(self):
        self.assertEqual(self.query("SELECT orders FROM mart.customers WHERE customer_unique_id = 'b1'"), [(2,)])
        self.assertEqual(
            self.query("SELECT customer_id, city, zip_code_prefix FROM core.customer_order_profiles "
                       "WHERE customer_unique_id = 'b1' ORDER BY customer_id"),
            [('c1', 'first', '00123'), ('c2', 'second', '00456')])
        self.assertEqual(self.query('SELECT count(*) FROM core.customers'), [(3,)])

    def test_empty_month_included(self):
        self.assertEqual(
            self.query("SELECT month::text, orders, revenue FROM mart.monthly_sales "
                       "WHERE month BETWEEN '2017-01-01' AND '2017-03-01' ORDER BY month"),
            [('2017-01-01', 1, Decimal('40')), ('2017-02-01', 0, Decimal('0')), ('2017-03-01', 2, Decimal('35'))])

    def test_status_not_delivery_date_defines_revenue(self):
        # o4 без даты вручения, но со статусом delivered — в выручке; отменённый o3 — нет.
        self.assertEqual(self.query('SELECT sum(price) FROM mart.delivered_items'), [(Decimal('75'),)])
        self.assertEqual(
            self.query("SELECT count(*) FROM mart.quality_issues WHERE issue_code = 'delivered_without_delivery_date'"),
            [(1,)])

    def test_reviews_keep_shared_id_and_latest_score(self):
        self.assertEqual(self.query('SELECT count(*) FROM core.order_reviews'), [(3,)])
        self.assertEqual(self.query("SELECT latest_review_score FROM mart.order_totals WHERE order_id = 'o1'"), [(5,)])

    def test_delivery_deadline_compared_by_date(self):
        self.assertEqual(
            self.query("SELECT order_id, delay_days, is_late FROM mart.order_totals "
                       "WHERE order_id IN ('o1', 'o2') ORDER BY order_id"),
            [('o1', 0, False), ('o2', 1, True)])

    def test_missing_payment_is_not_zero(self):
        self.assertEqual(
            self.query("SELECT payment_records, paid_amount, payment_delta FROM mart.order_totals WHERE order_id = 'o4'"),
            [(0, None, None)])

    def test_nonfinite_money_is_rejected_without_changing_model(self):
        fields = [
            ('order_items', 'price', "order_id = 'o1' AND order_item_id = '1'"),
            ('order_items', 'freight_value', "order_id = 'o1' AND order_item_id = '1'"),
            ('order_payments', 'payment_value', "order_id = 'o1' AND payment_sequential = '1'"),
        ]
        for table, field, condition in fields:
            for value in ('NaN', 'Infinity', '-Infinity'):
                with self.subTest(table=table, field=field, value=value):
                    before = fingerprint(self.dbname, 'core')
                    with connect(self.dbname) as conn, conn.cursor() as cur:
                        cur.execute(f'SELECT {field} FROM raw.{table} WHERE {condition}')
                        original = cur.fetchone()[0]
                        cur.execute(f'UPDATE raw.{table} SET {field} = %s WHERE {condition}', (value,))
                    dirty_raw = fingerprint(self.dbname, 'raw')
                    try:
                        result = build(self.dbname, success=False)
                        self.assertNotEqual(result.returncode, 0, 'Недопустимая денежная величина принята')
                        self.assertEqual(before, fingerprint(self.dbname, 'core'))
                        self.assertEqual(dirty_raw, fingerprint(self.dbname, 'raw'))
                    finally:
                        with connect(self.dbname) as conn, conn.cursor() as cur:
                            cur.execute(f'UPDATE raw.{table} SET {field} = %s WHERE {condition}', (original,))
                        build(self.dbname)

    def test_zero_revenue_keeps_categories_with_undefined_shares(self):
        original = self.query('SELECT order_id, order_item_id, price FROM raw.order_items')
        try:
            with connect(self.dbname) as conn, conn.cursor() as cur:
                cur.execute("UPDATE raw.order_items SET price = '0'")
            build(self.dbname)
            self.assertEqual(
                self.query('SELECT category_key, revenue, revenue_pct FROM mart.category_sales ORDER BY category_key'),
                [('__unknown__', Decimal('0'), None), ('known', Decimal('0'), None),
                 ('untranslated', Decimal('0'), None)])
        finally:
            with connect(self.dbname) as conn, conn.cursor() as cur:
                cur.executemany('UPDATE raw.order_items SET price = %s WHERE order_id = %s AND order_item_id = %s',
                                [(price, order_id, item_id) for order_id, item_id, price in original])
            build(self.dbname)

    def answer(self, name):
        return self.query((ROOT / 'answers' / name).read_text(encoding='utf-8'))

    def test_answer_price_history_breaks_ties_by_units(self):
        # У каждого товара одна цена; p1 продан двумя единицами — он и выбирается.
        self.assertEqual(self.answer('06_price_history.sql'),
                         [('p1', date(2017, 1, 15), Decimal('10.00'), 2)])

    def test_answer_status_funnel_counts_orders_without_items(self):
        self.assertEqual(self.answer('08_status_funnel.sql'),
                         [('delivered', 3, Decimal('75.00'), 0), ('canceled', 1, Decimal('25.00'), 0)])

    def test_answer_installments_by_payment_type(self):
        # Кредитная карта: 4, 1, 1 части → 2.00; ваучер: 1.
        self.assertEqual(self.answer('09b_payments_by_type.sql'),
                         [('credit_card', 3, Decimal('2.00')), ('voucher', 1, Decimal('1.00'))])

    def test_answer_review_uses_latest_score_and_keeps_empty_scores(self):
        # o1: отзывы 1 и 5, последний — 5; доставлен за 5 дней вовремя.
        # o2: оценка 3; доставлен за 4 дня, на день позже обещанного.
        self.assertEqual(self.answer('10_review_vs_delivery.sql'), [
            (1, 0, None, None), (2, 0, None, None),
            (3, 1, Decimal('4.00'), Decimal('100.00')),
            (4, 0, None, None),
            (5, 1, Decimal('5.00'), Decimal('0.00')),
        ])

    def test_rebuild_does_not_change_source(self):
        before = fingerprint(self.dbname, 'raw')
        build(self.dbname)
        self.assertEqual(before, fingerprint(self.dbname, 'raw'))

    def test_bad_input_rolls_back_model_and_keeps_raw(self):
        cases = [
            ('мусор вместо цены',
             "INSERT INTO raw.order_items(order_id, order_item_id, product_id, seller_id, price, freight_value) "
             "VALUES ('o1','9','p1','s1','oops','1')",
             "DELETE FROM raw.order_items WHERE order_item_id = '9'"),
            ('позиция несуществующего заказа',
             "INSERT INTO raw.order_items(order_id, order_item_id, product_id, seller_id, price, freight_value) "
             "VALUES ('missing','9','p1','s1','1','1')",
             "DELETE FROM raw.order_items WHERE order_id = 'missing'"),
            ('повтор ключа отзыва',
             "INSERT INTO raw.order_reviews(review_id, order_id, review_score) VALUES ('r1','o1','5')",
             "DELETE FROM raw.order_reviews WHERE review_id = 'r1' AND order_id = 'o1' AND review_creation_date IS NULL"),
            ('доставленный заказ без позиций (проверка качества уровня error)',
             "INSERT INTO raw.orders(order_id, customer_id, order_status, order_purchase_timestamp) "
             "VALUES ('o5','c4','delivered','2017-03-03 10:00')",
             "DELETE FROM raw.orders WHERE order_id = 'o5'"),
        ]
        for name, insert, cleanup in cases:
            with self.subTest(case=name):
                before = fingerprint(self.dbname, 'core')
                with connect(self.dbname) as conn, conn.cursor() as cur:
                    cur.execute(insert)
                dirty_raw = fingerprint(self.dbname, 'raw')
                try:
                    result = build(self.dbname, success=False)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('ERROR', result.stdout + result.stderr)
                    self.assertEqual(before, fingerprint(self.dbname, 'core'))
                    self.assertEqual(dirty_raw, fingerprint(self.dbname, 'raw'))
                finally:
                    with connect(self.dbname) as conn, conn.cursor() as cur:
                        cur.execute(cleanup)


if __name__ == '__main__':
    unittest.main()
