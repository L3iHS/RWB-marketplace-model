#!/usr/bin/env python3
"""Проверки изменённых данных в отдельной временной БД.
Никогда не изменяет raw/core рабочего marketplace. Требуется право CREATEDB.
Запуск: .venv/bin/python scripts/check_scenarios.py [--dsn ...]
"""
import argparse
import subprocess
import sys
from decimal import Decimal
import unittest
import uuid

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn
from build_model import ROOT, read_build_sql
from check_model import fingerprint

DSN = 'postgresql://hack:hack@localhost:5432/marketplace'


class ModelScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = 'hack_scenarios_' + uuid.uuid4().hex[:12]
        cls.admin = psycopg2.connect(DSN)
        cls.admin.autocommit = True
        cls.conn = None
        try:
            with cls.admin.cursor() as cur:
                cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.database)))
        except Exception:
            cls.admin.close()
            raise
        cls.addClassCleanup(cls.cleanup_database)
        cls.conn = psycopg2.connect(make_dsn(DSN, dbname=cls.database))
        cls.build_sql = read_build_sql()
        with cls.conn.cursor() as cur:
            cur.execute('CREATE SCHEMA raw')
            cur.execute((ROOT / 'scripts/init/02_raw_ddl.sql').read_text(encoding='utf-8'))
        cls.conn.commit()

    @classmethod
    def cleanup_database(cls):
        if cls.conn is not None:
            cls.conn.close()
        try:
            with cls.admin.cursor() as cur:
                cur.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(cls.database)))
        finally:
            cls.admin.close()

    def setUp(self):
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute((ROOT / 'tests/scenario_fixture.sql').read_text(encoding='utf-8'))
        self.conn.commit()
        self.build()

    def build(self):
        with self.conn.cursor() as cur:
            cur.execute(self.build_sql)
        self.conn.commit()

    def mutate(self, query, params=None):
        with self.conn.cursor() as cur:
            cur.execute(query, params)
        self.conn.commit()

    def rows(self, query, params=None):
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            result = cur.fetchall()
        self.conn.commit()
        return result

    def assert_rejected(self, message):
        # Ошибочный источник уже зафиксирован. Неудачная сборка должна оставить
        # предыдущий core и не исправлять/удалять записи даже в тестовом raw.
        with self.conn.cursor() as cur:
            old_core = fingerprint(cur, 'core')
            changed_raw = fingerprint(cur, 'raw')
        self.conn.commit()
        with self.assertRaisesRegex(psycopg2.Error, message):
            self.build()
        self.conn.rollback()
        with self.conn.cursor() as cur:
            self.assertEqual(fingerprint(cur, 'core'), old_core)
            self.assertEqual(fingerprint(cur, 'raw'), changed_raw)
        self.conn.commit()

    def test_multiple_payments_do_not_multiply_goods(self):
        self.mutate("INSERT INTO raw.order_payments (order_id,payment_sequential,payment_type,payment_installments,payment_value,_source_file) VALUES ('order-1','3','instant_test','1','5','fixture.csv')")
        self.build()
        self.assertEqual(self.rows("SELECT units,logical_lines,goods_amount,order_amount,paid_amount FROM mart.order_totals WHERE order_id='order-1'"), [(3,2,Decimal('250'),Decimal('275'),Decimal('280'))])
        self.assertEqual(self.rows("SELECT count(*) FROM mart.quality_issues WHERE issue_code='new_payment_type'"),[(1,)])
        self.assertEqual(self.rows("SELECT count(*) FROM mart.quality_issues WHERE issue_code='payment_amount_mismatch'"),[(1,)])

    def test_unknown_status_is_kept_and_not_revenue(self):
        self.mutate("UPDATE raw.orders SET order_status='fraud_review' WHERE order_id='order-1'")
        self.build()
        self.assertEqual(self.rows("SELECT count(*) FROM core.orders"),[(2,)])
        self.assertEqual(self.rows("SELECT count(*) FROM mart.delivered_items"),[(0,)])
        self.assertEqual(self.rows("SELECT count(*) FROM mart.quality_issues WHERE issue_code='new_order_status'"),[(1,)])

    def test_missing_category_and_missing_translation_keep_revenue(self):
        self.mutate("UPDATE raw.products SET product_category_name='category_without_translation' WHERE product_id='product-1'; UPDATE raw.products SET product_category_name='' WHERE product_id='product-2'")
        self.build()
        self.assertEqual(self.rows('SELECT sum(price) FROM mart.delivered_items'),[(Decimal('250'),)])
        self.assertEqual(self.rows("SELECT count(*) FROM mart.quality_issues WHERE issue_code='missing_category'"),[(1,)])
        self.assertEqual(self.rows("SELECT count(*) FROM mart.quality_issues WHERE issue_code='missing_category_translation'"),[(1,)])

    def test_repeated_review_id_and_customer_identity(self):
        self.assertEqual(self.rows('SELECT count(*) FROM core.order_reviews'),[(2,)])
        self.assertEqual(self.rows('SELECT count(*) FROM core.customers'),[(1,)])
        self.assertEqual(self.rows('SELECT city FROM core.customer_order_profiles ORDER BY customer_id'),[('city-one',),('city-two',)])

    def test_cli_error_after_loading_rolls_back_and_is_readable(self):
        # Тип integer корректен: preflight проходит. Ошибка CHECK появится
        # в конце загрузки, уже после TRUNCATE и INSERT остальных таблиц.
        self.mutate("UPDATE raw.order_reviews SET review_score='6' WHERE order_id='order-1'")
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/build_model.py'),
            '--dsn', make_dsn(DSN, dbname=self.database)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('order_reviews_score_check', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(self.rows('SELECT count(*) FROM core.order_payments'), [(2,)])
        self.assertEqual(self.rows('SELECT score FROM core.order_reviews ORDER BY order_id'), [(5,), (2,)])

    def test_duplicate_payment_is_rejected(self):
        self.mutate('INSERT INTO raw.order_payments SELECT * FROM raw.order_payments LIMIT 1')
        self.assert_rejected(r'Повтор ключа raw.order_payments')

    def test_duplicate_review_pair_is_rejected(self):
        self.mutate('INSERT INTO raw.order_reviews SELECT * FROM raw.order_reviews LIMIT 1')
        self.assert_rejected(r'Повтор ключа raw.order_reviews')

    def test_missing_foreign_key_is_rejected(self):
        self.mutate("UPDATE raw.order_items SET seller_id='nonexistent-seller' WHERE order_item_id='1'")
        self.assert_rejected(r'Нет связи raw.order_items.seller_id')

    def test_invalid_date_is_rejected(self):
        self.mutate("UPDATE raw.orders SET order_purchase_timestamp='not-a-date' WHERE order_id='order-1'")
        self.assert_rejected(r'Некорректный тип timestamp в raw.orders.order_purchase_timestamp')

    def test_blank_identifier_is_rejected(self):
        self.mutate("UPDATE raw.customers SET customer_unique_id='  ' WHERE customer_id='customer-1'")
        self.assert_rejected(r'Пустое обязательное поле raw.customers.customer_unique_id')

    def test_nonfinite_money_is_rejected(self):
        self.mutate("UPDATE raw.order_items SET price='NaN' WHERE order_item_id='1'")
        self.assert_rejected(r'Денежная сумма должна быть конечным числом')

    def test_optional_blank_date_becomes_null(self):
        self.mutate("UPDATE raw.orders SET order_approved_at='   ' WHERE order_id='order-1'")
        self.build()
        self.assertEqual(self.rows("SELECT approved_at FROM core.orders WHERE order_id='order-1'"),[(None,)])

    def test_category_ids_survive_add_remove_return_and_translation(self):
        before = dict(self.rows('SELECT name_pt, category_id FROM core.categories'))
        # Новое имя сортируется раньше старого — старая версия перенумеровывала ID.
        category = '000_new_' + uuid.uuid4().hex[:8]
        self.mutate('INSERT INTO raw.products (product_id,product_category_name) VALUES (%s,%s)',('new-product',category))
        self.build()
        added = dict(self.rows('SELECT name_pt, category_id FROM core.categories'))
        for name, key in before.items():
            self.assertEqual(added[name], key)
        new_id = added[category]
        self.mutate("DELETE FROM raw.products WHERE product_id='new-product'")
        self.build()
        self.assertEqual(self.rows('SELECT category_id FROM core.categories WHERE name_pt=%s',(category,)),[(new_id,)])
        self.mutate('INSERT INTO raw.products (product_id,product_category_name) VALUES (%s,%s)',('new-product',category))
        self.mutate('INSERT INTO raw.product_category_translation (product_category_name,product_category_name_english) VALUES (%s,%s)',(category,'New translation'))
        self.build()
        self.assertEqual(self.rows('SELECT category_id,name_en FROM core.categories WHERE name_pt=%s',(category,)),[(new_id,'New translation')])


def main():
    global DSN
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn',default=DSN)
    args = parser.parse_args()
    DSN = args.dsn
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ModelScenarios)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
