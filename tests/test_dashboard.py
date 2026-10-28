"""HTTP-контракт дашборда на изолированной настоящей PostgreSQL."""
import csv
import importlib
import io
import unittest
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

import test_model as fixtures

api = importlib.import_module('backend.app')


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.EdgeCases.setUpClass()
        cls.dbname = fixtures.EdgeCases.dbname
        cls.addClassCleanup(fixtures.EdgeCases.doClassCleanups)

    def setUp(self):
        # Не используем marketplace: каждый HTTP-запрос читает только rwb_test_*.
        with fixtures.connect(self.dbname) as conn, conn.cursor() as cur:
            cur.execute('DROP SCHEMA IF EXISTS ops CASCADE')
        fixtures.build(self.dbname)
        self.connection = patch.object(api, 'connect_database', lambda: fixtures.connect(self.dbname))
        self.connection.start()
        self.addCleanup(self.connection.stop)
        self.client = TestClient(api.app)
        self.addCleanup(self.client.close)

    def dashboard(self, **params):
        response = self.client.get('/api/dashboard', params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def execute(self, statement, params=None):
        with fixtures.connect(self.dbname) as conn, conn.cursor() as cur:
            cur.execute(statement, params)

    def publish(self, version, sequence):
        self.execute((fixtures.ROOT / 'scripts/sql/ingestion.sql').read_text())
        self.execute('''INSERT INTO ops.dataset_versions
            (version_id,dataset_sha256,transform_sha256,schema_sha256,source_id,sequence,
             kind,archive_path,manifest,summary)
            VALUES (%s,%s,'transform','schema','test',%s,'synthetic','test','{}','{}');
            INSERT INTO ops.current_dataset(singleton,version_id) VALUES (true,%s)
            ON CONFLICT(singleton) DO UPDATE SET version_id=excluded.version_id''',
                     (version, version, sequence, version))

    def test_metrics_preserve_money_and_business_grains(self):
        data = self.dashboard()
        self.assertEqual(data['summary'], {
            'revenue_brl': '75.00', 'delivered_orders': 3, 'average_check_brl': '27.33',
            'buyers': 3, 'repeat_buyers': 1, 'repeat_pct': '33.33',
        })
        self.assertEqual(data['context'], {
            'dataset_version': 'original', 'kind': 'original', 'currency': 'BRL',
            'published_at': None, 'data_from': '2017-01-15', 'data_to': '2017-03-02',
        })
        self.assertEqual(data['options'], {
            'states': ['RJ', 'SP'], 'date_min': '2017-01-15', 'date_max': '2017-03-02',
        })
        self.assertEqual(data['orders_total'], 4)
        self.assertEqual([(r['month'], r['delivered_orders'], Decimal(r['revenue_brl']))
                          for r in data['monthly']], [
            ('2017-01-01', 1, Decimal('40')), ('2017-02-01', 0, Decimal('0')),
            ('2017-03-01', 2, Decimal('35')),
        ])
        self.assertEqual([(r['seller_id'], r['orders'], r['units'], Decimal(r['revenue_brl']))
                          for r in data['sellers']], [
            ('s1', 3, 4, Decimal('55')), ('s2', 1, 1, Decimal('20')),
        ])
        self.assertEqual(sum(Decimal(r['revenue_brl']) for r in data['categories']), Decimal('75'))
        self.assertEqual(sum(r['orders'] for r in data['statuses']), 4)
        orders = {r['order_id']: r for r in data['orders']}
        self.assertEqual(orders['o1']['latest_review_score'], 5)
        self.assertEqual(orders['o1']['units'], 3)
        self.assertEqual(orders['o3']['status_code'], 'canceled')
        self.assertEqual(orders['o4']['delivery_days'], None)
        delivery = {r['state']: r for r in data['delivery']}
        self.assertEqual(delivery['SP'], {
            'state': 'SP', 'orders': 2, 'known_delivery_dates': 1, 'average_days': '5.00',
            'late_orders': 0, 'late_pct': '0.00', 'missing_dates': 1,
        })
        self.assertEqual(delivery['RJ']['late_pct'], '100.00')

    def test_filter_end_date_is_inclusive_and_quality_is_global(self):
        full = self.dashboard()
        selected = self.dashboard(date_from='2017-03-01', date_to='2017-03-01', state=' rj ')
        self.assertEqual(selected['filters'], {
            'date_from': '2017-03-01', 'date_to': '2017-03-01', 'state': 'RJ',
        })
        self.assertEqual(selected['orders_total'], 1)
        self.assertEqual(selected['summary']['revenue_brl'], '30.00')
        self.assertEqual(selected['orders'][0]['order_id'], 'o2')
        self.assertEqual(selected['quality'], full['quality'])
        self.assertEqual(selected['options'], full['options'])
        canceled = self.dashboard(date_from='2017-03-01', date_to='2017-03-01', state='SP')
        self.assertEqual(canceled['summary']['revenue_brl'], '0')
        self.assertEqual(canceled['summary']['delivered_orders'], 0)
        self.assertIsNone(canceled['summary']['average_check_brl'])
        self.assertEqual(canceled['summary']['buyers'], 1)

    def test_empty_slice_has_zero_counts_and_null_undefined_ratios(self):
        data = self.dashboard(date_from='2025-01-01', date_to='2025-01-31')
        self.assertEqual(data['summary'], {
            'revenue_brl': '0', 'delivered_orders': 0, 'average_check_brl': None,
            'buyers': 0, 'repeat_buyers': 0, 'repeat_pct': None,
        })
        self.assertEqual(data['orders_total'], 0)
        for report in ('monthly', 'orders', 'sellers', 'categories', 'statuses', 'delivery'):
            self.assertEqual(data[report], [], report)
        self.assertTrue(data['quality'])
        self.assertEqual(self.dashboard(date_from='', date_to='', state='')['orders_total'], 4)

    def test_invalid_filters_and_report_have_string_errors(self):
        invalid = [
            {'date_from': '20170115'}, {'date_to': '2017-02-30'},
            {'date_from': '2017-03-01', 'date_to': '2017-01-01'},
            {'state': 'ZZ'}, {'state': "SP' OR true --"},
        ]
        for params in invalid:
            with self.subTest(params=params):
                response = self.client.get('/api/dashboard', params=params)
                self.assertEqual(response.status_code, 422)
                self.assertIsInstance(response.json()['detail'], str)
        for params in ({'report': 'orders'}, {'report': 'sql', 'expected_version': 'original'}):
            response = self.client.get('/api/export', params=params)
            self.assertEqual(response.status_code, 422)
            self.assertIsInstance(response.json()['detail'], str)

    def test_publication_context_and_version_guard(self):
        self.publish('version-one', 1)
        data = self.dashboard()
        self.assertEqual(data['context']['dataset_version'], 'version-one')
        self.assertEqual(data['context']['kind'], 'synthetic')
        self.assertIsNotNone(data['context']['published_at'])
        self.publish('version-two', 2)
        stale = self.client.get('/api/export', params={'report': 'orders', 'expected_version': 'version-one'})
        self.assertEqual(stale.status_code, 409)
        self.assertIsInstance(stale.json()['detail'], str)
        current = self.client.get('/api/export', params={'report': 'orders', 'expected_version': 'version-two'})
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.headers['x-dataset-version'], 'version-two')
        self.assertIn('orders-version-two.csv', current.headers['content-disposition'])
        self.assertIn('charset=utf-8', current.headers['content-type'])

    def test_export_is_full_while_screen_has_latest_fifty_orders(self):
        self.execute('''INSERT INTO raw.orders
            (order_id,customer_id,order_status,order_purchase_timestamp)
            SELECT 'extra-' || n, 'c1', 'canceled', '2017-03-01 23:59:59'
            FROM generate_series(1,55) AS n''')
        self.addCleanup(self.execute, "DELETE FROM raw.orders WHERE order_id LIKE 'extra-%'")
        fixtures.build(self.dbname)
        data = self.dashboard()
        self.assertEqual(data['orders_total'], 59)
        self.assertEqual(len(data['orders']), 50)
        params = {'report': 'orders', 'expected_version': data['context']['dataset_version']}
        response = self.client.get('/api/export', params=params)
        self.assertEqual(response.status_code, 200, response.text)
        exported = list(csv.DictReader(io.StringIO(response.text)))
        self.assertEqual(len(exported), 59)
        self.assertEqual({r['order_id'] for r in exported},
                         {f'extra-{n}' for n in range(1, 56)} | {'o1', 'o2', 'o3', 'o4'})
        filtered = self.client.get('/api/export', params={**params, 'state': 'RJ'})
        self.assertEqual([r['order_id'] for r in csv.DictReader(io.StringIO(filtered.text))], ['o2'])

    def test_all_csv_reports_match_screen_rows_and_keep_column_headers(self):
        data = self.dashboard()
        for report in api.REPORTS:
            with self.subTest(report=report):
                response = self.client.get('/api/export', params={
                    'report': report, 'expected_version': data['context']['dataset_version'],
                })
                self.assertEqual(response.status_code, 200, response.text)
                reader = csv.DictReader(io.StringIO(response.text))
                self.assertEqual(reader.fieldnames, list(data[report][0]))
                self.assertEqual(len(list(reader)), len(data[report]))

    def test_response_remains_one_repeatable_read_snapshot_during_update(self):
        original_records = api.records
        changed = False

        def update_after_summary(cur, statement, params=None):
            nonlocal changed
            result = original_records(cur, statement, params)
            if 'buyers AS' in statement and not changed:
                changed = True
                self.execute("UPDATE core.order_items SET price=20 WHERE order_id='o1' AND order_item_id=1")
            return result

        with api.snapshot() as cur:
            cur.execute("SELECT current_setting('transaction_isolation'), current_setting('transaction_read_only')")
            self.assertEqual(cur.fetchone(), ('repeatable read', 'on'))
        with patch.object(api, 'records', update_after_summary):
            data = self.dashboard()
        self.assertTrue(changed)
        self.assertEqual(data['summary']['revenue_brl'], '75.00')
        self.assertEqual(sum(Decimal(r['revenue_brl']) for r in data['sellers']), Decimal('75'))
        self.assertEqual(sum(Decimal(r['revenue_brl']) for r in data['categories']), Decimal('75'))
        self.assertEqual(Decimal(self.dashboard()['summary']['revenue_brl']), Decimal('85'))

    def test_questions_execute_fixed_sql_and_export_even_empty_results(self):
        response = self.client.get('/api/questions', params={'state': 'RJ', 'date_from': '2025-01-01'})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['context']['dataset_version'], 'original')
        self.assertEqual([q['id'] for q in data['questions']], ['6', '7', '8', '9a', '9b', '10'])
        for question in data['questions']:
            with self.subTest(question=question['id']):
                filename = api.QUESTIONS[question['id']][1]
                statement = (fixtures.ROOT / 'answers' / filename).read_text(encoding='utf-8')
                self.assertEqual(question['sql_file'], f'answers/{filename}')
                self.assertEqual(question['sql'], statement)
                self.assertEqual(question['rows'], api.serializable(fixtures.rows(self.dbname, statement)))
                self.assertEqual(question['row_count'], len(question['rows']))
                exported = self.client.get(f"/api/questions/{question['id']}/export", params={
                    'expected_version': data['context']['dataset_version'],
                })
                self.assertEqual(exported.status_code, 200, exported.text)
                reader = csv.reader(io.StringIO(exported.text))
                self.assertEqual(next(reader), question['columns'])
                self.assertEqual(len(list(reader)), question['row_count'])
                self.assertEqual(exported.headers['x-dataset-version'], 'original')
        questions = {q['id']: q for q in data['questions']}
        self.assertEqual(questions['6']['rows'], [['p1', '2017-01-15', '10.00', 2]])
        self.assertEqual(questions['7']['rows'], [])
        self.assertEqual(questions['9a']['rows'], [])
        self.assertEqual(questions['9b']['rows'][0], ['credit_card', 3, '2.00'])
        self.assertEqual(questions['10']['rows'][0], [1, 0, None, None])
        self.publish('questions-new-version', 1)
        stale = self.client.get('/api/questions/6/export', params={'expected_version': 'original'})
        self.assertEqual(stale.status_code, 409)
        unknown = self.client.get('/api/questions/not-a-query/export', params={'expected_version': 'original'})
        self.assertEqual(unknown.status_code, 404)

    def test_questions_share_one_snapshot_during_concurrent_update(self):
        original_sql = api.question_sql
        changed = False

        def update_before_second_question(question_id):
            nonlocal changed
            if question_id == '7' and not changed:
                changed = True
                self.execute('''UPDATE core.order_payments SET installments=7
                    WHERE order_id='o1' AND payment_sequential=1''')
            return original_sql(question_id)

        with patch.object(api, 'question_sql', update_before_second_question):
            response = self.client.get('/api/questions')
        self.assertEqual(response.status_code, 200, response.text)
        question = next(q for q in response.json()['questions'] if q['id'] == '9b')
        self.assertTrue(changed)
        self.assertEqual(question['rows'][0], ['credit_card', 3, '2.00'])
        fresh = self.client.get('/api/questions').json()
        question = next(q for q in fresh['questions'] if q['id'] == '9b')
        self.assertEqual(question['rows'][0], ['credit_card', 3, '3.00'])

    def test_health_checks_model_readiness(self):
        self.assertEqual(self.client.get('/api/health').json(), {'status': 'ok'})
        with patch.object(api, 'connect_database', lambda: fixtures.connect('postgres')):
            response = self.client.get('/api/health')
        self.assertEqual(response.status_code, 503)
        self.assertIsInstance(response.json()['detail'], str)

    def test_history_route_uses_model_and_bound_identifiers(self):
        response = self.client.get('/api/history', params={'product_id': 'p1', 'order_id': 'o1'})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['context']['dataset_version'], 'original')
        self.assertEqual(data['summary'], {
            'products_with_changes': 0, 'category_versions': 4,
            'frozen_order_addresses': 4, 'addresses_different_from_profile': 0,
        })
        self.assertEqual(data['selected_product'], 'p1')
        self.assertEqual(len(data['category_history']), 1)
        self.assertIsInstance(data['category_history'][0]['observed_from'], str)
        self.assertTrue(all(isinstance(row['price'], str) for row in data['product_orders']))
        self.assertEqual([row['order_id'] for row in data['orders']], ['o1'])
        injected = self.client.get('/api/history', params={
            'product_id': "p1' OR true --", 'order_id': "o1' OR true --",
        })
        self.assertEqual(injected.status_code, 200)
        self.assertEqual(injected.json()['category_history'], [])
        self.assertEqual(injected.json()['orders'], [])
        invalid = self.client.get('/api/history', params={'product_id': 'p' * 129})
        self.assertEqual(invalid.status_code, 422)
        self.assertIsInstance(invalid.json()['detail'], str)


if __name__ == '__main__':
    unittest.main()
