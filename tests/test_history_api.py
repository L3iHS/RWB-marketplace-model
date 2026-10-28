"""Проверки данных вкладки истории на изолированной PostgreSQL."""
import unittest
from decimal import Decimal

from backend.history import history_data
import test_model as fixtures


class HistoryDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.EdgeCases.setUpClass()
        cls.dbname = fixtures.EdgeCases.dbname
        cls.addClassCleanup(fixtures.EdgeCases.doClassCleanups)

    def setUp(self):
        fixtures.build(self.dbname)

    def data(self, **params):
        with fixtures.connect(self.dbname) as conn, conn.cursor() as cur:
            cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            return history_data(cur, **params)

    def execute(self, statement):
        with fixtures.connect(self.dbname) as conn, conn.cursor() as cur:
            cur.execute(statement)

    def test_initial_history_is_one_observed_version_without_invented_changes(self):
        before = fixtures.fingerprint(self.dbname, 'core')
        data = self.data()
        self.assertEqual(data['summary'], dict(products_with_changes=0, category_versions=4,
            frozen_order_addresses=4, addresses_different_from_profile=0))
        self.assertEqual(data['selected_product'], 'p1')
        self.assertEqual(len(data['category_history']), 1)
        self.assertIsNone(data['category_history'][0]['observed_to'])
        self.assertEqual([row['order_id'] for row in data['product_orders']], ['o3', 'o1', 'o1'])
        self.assertEqual(data['product_orders'][1]['price'], Decimal('10.00'))
        self.assertEqual(data['product_orders'][1]['category_at_order'], 'Known')
        self.assertEqual(fixtures.fingerprint(self.dbname, 'core'), before)

    def test_old_positions_keep_original_category_and_new_positions_use_new_version(self):
        self.execute('''INSERT INTO core.categories(category_key,name_pt) VALUES ('new','new');
            UPDATE core.product_category_history SET observed_to=observed_from+interval '1 day'
                WHERE product_id='p1';
            INSERT INTO core.product_category_history
                SELECT product_id,2,'new',observed_to,NULL FROM core.product_category_history
                WHERE product_id='p1';
            UPDATE core.products SET category_key='new' WHERE product_id='p1';
            UPDATE core.order_items SET category_version_no=2 WHERE order_id='o3' ''')
        data = self.data(product_id='p1')
        self.assertEqual(data['summary']['products_with_changes'], 1)
        self.assertEqual(data['summary']['category_versions'], 5)
        self.assertEqual(data['products'][0], dict(product_id='p1', versions=2, current_category='new'))
        self.assertEqual([row['version_no'] for row in data['category_history']], [1, 2])
        self.assertEqual([(row['category_at_order'], row['current_category'], row['version_no'])
            for row in data['product_orders']], [('new', 'new', 2), ('Known', 'new', 1), ('Known', 'new', 1)])

    def test_changed_address_is_first_and_order_filter_is_bound(self):
        self.execute("UPDATE core.customer_order_profiles SET city=NULL,state='MG' WHERE customer_id='c1'")
        data = self.data()
        self.assertEqual(data['summary']['addresses_different_from_profile'], 1)
        self.assertEqual(data['orders'][0]['order_id'], 'o1')
        self.assertEqual(data['orders'][0]['snapshot_city'], 'first')
        self.assertEqual(data['orders'][0]['snapshot_state'], 'SP')
        self.assertIsNone(data['orders'][0]['current_city'])
        self.assertEqual(data['orders'][0]['current_state'], 'MG')
        self.assertEqual([row['order_id'] for row in self.data(order_id='o2')['orders']], ['o2'])
        self.assertEqual(self.data(order_id="o1' OR true --")['orders'], [])
        self.assertEqual(self.data(product_id="p1' OR true --")['category_history'], [])

    def test_empty_model_returns_zero_counts_and_empty_lists(self):
        self.execute('TRUNCATE core.products,core.orders,core.product_category_history CASCADE')
        data = self.data()
        self.assertIsNone(data['selected_product'])
        self.assertEqual(set(data['summary'].values()), {0})
        for name in ('products', 'category_history', 'product_orders', 'orders'):
            self.assertEqual(data[name], [])


if __name__ == '__main__':
    unittest.main()
