"""Вброс: новые снимки не переписывают категорию/адрес старых фактов."""
import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_model as fixtures
from batches import FILES, seal_batch
from ingestion import ingest, status


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.EdgeCases.setUpClass()
        cls.dbname = fixtures.EdgeCases.dbname
        cls.addClassCleanup(fixtures.EdgeCases.doClassCleanups)
        with fixtures.connect(cls.dbname) as conn, conn.cursor() as cur:
            cls.source = {}
            for name, (table, columns) in FILES.items():
                cur.execute('SELECT ' + ','.join(columns) + ' FROM raw.' + table)
                cls.source[table] = [dict(zip(columns, values)) for values in cur.fetchall()]

    def setUp(self):
        with fixtures.connect(self.dbname) as conn, conn.cursor() as cur:
            cur.execute('DROP SCHEMA IF EXISTS ops CASCADE')
        fixtures.build(self.dbname)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = {table: [dict(row) for row in rows] for table, rows in self.source.items()}

    def publish(self, sequence):
        directory = self.root / str(sequence)
        directory.mkdir()
        for name, (table, columns) in FILES.items():
            with (directory / name).open('w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, columns, lineterminator='\n')
                writer.writeheader()
                writer.writerows(self.data[table])
        seal_batch(directory, 'history-test', sequence, 'synthetic')
        return ingest(directory, self.root / 'archive', self.dbname)

    def query(self, statement):
        return fixtures.rows(self.dbname, statement)

    def change_category(self, category):
        for row in self.data['products']:
            if row['product_id'] == 'p1':
                row['product_category_name'] = category

    def add_order(self, order='o5', customer='c1'):
        self.data['orders'].append(dict(order_id=order, customer_id=customer, order_status='delivered',
            order_purchase_timestamp='2017-04-01 10:00:00', order_approved_at='',
            order_delivered_carrier_date='', order_delivered_customer_date='2017-04-05 10:00:00',
            order_estimated_delivery_date='2017-04-04 00:00:00'))
        self.data['order_items'].append(dict(order_id=order, order_item_id='1', product_id='p1',
            seller_id='s1', shipping_limit_date='', price='7.00', freight_value='1.00'))
        self.data['order_payments'].append(dict(order_id=order, payment_sequential='1',
            payment_type='credit_card', payment_installments='1', payment_value='8.00'))

    def test_category_change_keeps_old_sales_and_assigns_new_sales_to_new_category(self):
        before = self.query('SELECT category_key,revenue FROM mart.category_sales ORDER BY 1')
        self.change_category('new-category')
        self.assertEqual(self.publish(1)['status'], 'published')
        self.assertEqual(self.query('SELECT category_key,revenue FROM mart.category_sales ORDER BY 1'), before)
        self.assertEqual(self.query("SELECT category_key FROM core.products WHERE product_id='p1'"), [('new-category',)])
        self.add_order()
        self.assertEqual(self.publish(2)['status'], 'published')
        self.assertEqual(self.query("SELECT category_key,price FROM mart.delivered_items WHERE order_id='o5'"), [('new-category', 7)])
        self.assertEqual(self.query("SELECT revenue FROM mart.category_sales WHERE category_key='known'"), [(40,)])
        self.assertEqual(self.query("SELECT version_no,category_key,observed_to IS NULL FROM core.product_category_history WHERE product_id='p1' ORDER BY version_no"),
                         [(1, 'known', False), (2, 'new-category', True)])

    def test_return_to_previous_category_creates_another_version(self):
        self.change_category('new-category')
        self.assertEqual(self.publish(1)['status'], 'published')
        self.change_category('known')
        self.add_order()
        self.assertEqual(self.publish(2)['status'], 'published')
        self.assertEqual(self.query("SELECT category_version_no FROM core.order_items WHERE order_id='o5'"), [(3,)])
        self.assertEqual(self.query("SELECT category_version_no FROM core.order_items WHERE order_id='o1' AND product_id='p1'"), [(1,), (1,)])

    def test_address_change_keeps_old_order_but_new_order_uses_new_address(self):
        for row in self.data['customers']:
            if row['customer_id'] == 'c1':
                row.update(customer_city='new-city', customer_state='MG', customer_zip_code_prefix='99999')
        self.add_order()
        self.assertEqual(self.publish(1)['status'], 'published')
        self.assertEqual(self.query("SELECT state FROM core.customer_order_profiles WHERE customer_id='c1'"), [('MG',)])
        self.assertEqual(self.query("SELECT order_id,customer_city,customer_state FROM mart.order_totals WHERE order_id IN ('o1','o5') ORDER BY order_id"),
                         [('o1', 'first', 'SP'), ('o5', 'new-city', 'MG')])
        self.assertEqual(self.query("SELECT zip_code_prefix FROM core.order_addresses WHERE order_id='o1'"), [('00123',)])

    def test_same_person_new_profile_keeps_both_order_addresses(self):
        self.data['customers'].append(dict(customer_id='c5', customer_unique_id='b1',
            customer_zip_code_prefix='88888', customer_city='moved', customer_state='MG'))
        self.add_order(customer='c5')
        self.assertEqual(self.publish(1)['status'], 'published')
        self.assertEqual(self.query("SELECT customer_unique_id,orders FROM mart.customers WHERE customer_unique_id='b1'"), [('b1', 3)])
        self.assertEqual(self.query("SELECT order_id,customer_state FROM mart.order_totals WHERE order_id IN ('o1','o2','o5') ORDER BY order_id"),
                         [('o1', 'SP'), ('o2', 'RJ'), ('o5', 'MG')])

    def test_failed_publication_rolls_back_category_history_and_addresses(self):
        before = fixtures.fingerprint(self.dbname, 'core')
        self.change_category('new-category')
        self.add_order()
        with patch('ingestion.check_model', side_effect=RuntimeError('simulated failure')):
            result = self.publish(1)
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(fixtures.fingerprint(self.dbname, 'core'), before)
        self.assertIsNone(status(self.dbname)['current'])

    def test_initial_observed_time_comes_from_raw_and_rebuild_is_deterministic(self):
        self.assertEqual(self.query("SELECT h.observed_from=r._loaded_at FROM core.product_category_history h JOIN raw.products r USING(product_id) WHERE h.product_id='p1'"), [(True,)])
        before = fixtures.fingerprint(self.dbname, 'core')
        fixtures.build(self.dbname)
        self.assertEqual(fixtures.fingerprint(self.dbname, 'core'), before)


if __name__ == '__main__':
    unittest.main()
