"""Ручное демо: HTTP/поток на mock, CSV-сценарий без изменения исходной базы."""
import csv
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
demo = importlib.import_module('backend.demo')
from batches import FILES, sha256  # noqa: E402
from simulate import generate, read_rows  # noqa: E402


class DemoControllerTests(unittest.TestCase):
    def setUp(self):
        demo._running = False
        demo._last_error = None
        self.status = dict(state='ready', day=2, total_days=5, database=demo.DEMO_DATABASE,
                           message='ready', version_id='v2', summary={'new_orders': 20})
        app = FastAPI()
        app.include_router(demo.router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_post_starts_exactly_one_thread_and_guards_concurrent_click(self):
        with patch.object(demo, 'published_status', return_value=self.status), \
             patch.object(demo, 'Thread') as thread:
            first = self.client.post('/api/demo/advance')
            self.assertEqual(first.status_code, 202)
            self.assertEqual(first.json()['state'], 'running')
            self.assertEqual(first.json()['day'], 2)
            thread.assert_called_once_with(target=demo.advance_one_day, name='dashboard-demo', daemon=True)
            thread.return_value.start.assert_called_once()
            second = self.client.post('/api/demo/advance')
            self.assertEqual(second.status_code, 409)
            self.assertEqual(self.client.get('/api/demo/status').json()['state'], 'running')

    def test_complete_does_not_start_a_thread(self):
        with patch.object(demo, 'published_status', return_value=dict(self.status, state='complete', day=5)), \
             patch.object(demo, 'Thread') as thread:
            response = self.client.post('/api/demo/advance')
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()['state'], 'complete')
            thread.assert_not_called()

    def test_restart_status_is_recovered_from_published_sequence_and_closes_connection(self):
        conn = MagicMock()
        with patch.object(demo, 'database_exists', return_value=True), \
             patch.object(demo, 'connect', return_value=conn) as connect, \
             patch.object(demo, 'current_version', return_value={
                 'sequence': 4, 'version_id': 'persisted-v4', 'summary': {'new_orders': 20}}):
            result = self.client.get('/api/demo/status').json()
        self.assertEqual((result['state'], result['day'], result['version_id']), ('ready', 4, 'persisted-v4'))
        connect.assert_called_once_with('marketplace_demo_dashboard')
        conn.close.assert_called_once()

    def test_database_creation_never_drops_resets_or_terminates_users(self):
        with patch.object(demo, 'database_exists', return_value=False), \
             patch.object(demo.subprocess, 'run', return_value=MagicMock(returncode=0)) as run:
            demo.ensure_database()
        command = run.call_args.args[0]
        self.assertEqual(command[1:], [str(ROOT / 'run.py'), 'demo-init', '--database', 'marketplace_demo_dashboard'])
        self.assertNotRegex(' '.join(command), 'DROP|RESET|terminate')

    def test_existing_database_is_not_changed(self):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (13,)
        with patch.object(demo, 'database_exists', return_value=True), \
             patch.object(demo, 'connect', return_value=conn), \
             patch.object(demo.subprocess, 'run') as run:
            demo.ensure_database()
        run.assert_not_called()
        self.assertEqual(conn.cursor.return_value.__enter__.return_value.execute.call_count, 1)
        conn.close.assert_called_once()

    def test_worker_ingests_only_the_next_fixed_batch_and_reuses_existing_feed(self):
        with tempfile.TemporaryDirectory() as temporary:
            incoming = Path(temporary) / 'incoming'
            (incoming / 'batch-003').mkdir(parents=True)
            (incoming / 'batch-003/manifest.json').write_text('{}')
            with patch.object(demo, 'INCOMING', incoming), \
                 patch.object(demo, 'ensure_database') as ensure, \
                 patch.object(demo, 'published_status', return_value=self.status), \
                 patch.object(demo, 'generate') as generate_mock, \
                 patch.object(demo, 'ingest', return_value={'status': 'published'}) as ingest:
                demo._running = True
                demo.advance_one_day()
            ensure.assert_called_once()
            generate_mock.assert_not_called()
            ingest.assert_called_once_with(incoming / 'batch-003', demo.ARCHIVE,
                                           dbname='marketplace_demo_dashboard')
            self.assertFalse(demo._running)

    def test_errors_do_not_expose_connection_secrets(self):
        with patch.object(demo, 'published_status', side_effect=RuntimeError('password=top-secret')):
            result = self.client.get('/api/demo/status').json()
            failed_post = self.client.post('/api/demo/advance')
            self.assertEqual(failed_post.status_code, 503)
            self.assertNotIn('top-secret', failed_post.text)
        self.assertEqual(result['state'], 'error')
        self.assertNotIn('top-secret', json.dumps(result))
        with patch.object(demo, 'ensure_database', side_effect=RuntimeError('postgres://user:top-secret@host')), \
             patch.object(demo.logger, 'exception'):
            demo.advance_one_day()
        with patch.object(demo, 'published_status', return_value=self.status):
            result = self.client.get('/api/demo/status').json()
        self.assertEqual(result['day'], 2)
        self.assertEqual(result['state'], 'error')
        self.assertNotIn('top-secret', json.dumps(result))


class DemoSimulationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        rows = {
            'products': [dict(product_id='p0', product_category_name='food')],
            'sellers': [dict(seller_id='s0', seller_city='santos', seller_state='SP')],
            'customers': [dict(customer_id='c0', customer_unique_id='b0', customer_zip_code_prefix='12345',
                               customer_city='santos', customer_state='SP'),
                          dict(customer_id='c1', customer_unique_id='b1', customer_zip_code_prefix='23456',
                               customer_city='rio', customer_state='RJ')],
            'orders': [dict(order_id='o0', customer_id='c0', order_status='delivered',
                            order_purchase_timestamp='2018-01-01 10:00:00')],
            'order_reviews': [dict(review_id='r0', order_id='o0', review_score='5',
                                   review_creation_date='2018-01-02 10:00:00')],
            'order_items': [dict(order_id='o0', order_item_id='1', product_id='p0', seller_id='s0',
                                 price='10', freight_value='1')],
            'order_payments': [dict(order_id='o0', payment_sequential='1', payment_type='credit_card',
                                    payment_installments='1', payment_value='11')],
            'product_category_translation': [dict(product_category_name='food', product_category_name_english='Food'),
                                             dict(product_category_name='toys', product_category_name_english='Toys')],
        }
        for name, (table, columns) in FILES.items():
            with (self.source / name).open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, columns, lineterminator='\r\n')
                writer.writeheader()
                writer.writerows(rows[table])

    def test_history_changes_on_day_three_and_original_csv_bytes_are_preserved(self):
        before = {name: sha256(self.source / name) for name in FILES}
        report = generate(self.source, self.root / 'history', orders_per_day=4, with_history=True)
        second, third = self.root / 'history/batch-002', self.root / 'history/batch-003'
        scenario = report['snapshots'][2]['history_scenario']
        self.assertTrue(scenario['applied'])
        self.assertFalse(report['snapshots'][1]['history_scenario']['applied'])
        product_id = scenario['product_id']
        self.assertEqual(next(row for row in read_rows(second, 'products') if row['product_id'] == product_id)['product_category_name'], 'food')
        self.assertEqual(next(row for row in read_rows(third, 'products') if row['product_id'] == product_id)['product_category_name'], 'toys')
        customer_id = scenario['customer_id']
        old = next(row for row in read_rows(second, 'customers') if row['customer_id'] == customer_id)
        new = next(row for row in read_rows(third, 'customers') if row['customer_id'] == customer_id)
        self.assertNotEqual(old['customer_state'], new['customer_state'])
        self.assertNotEqual(old['customer_city'], new['customer_city'])
        self.assertEqual(old['customer_unique_id'], new['customer_unique_id'])
        for name in FILES:
            self.assertEqual(sha256(self.source / name), before[name])
            for snapshot in report['snapshots']:
                self.assertTrue((self.root / 'history' / snapshot['directory'] / name).read_bytes()
                                .startswith((self.source / name).read_bytes()))
        manifest = json.loads((third / 'manifest.json').read_text())
        self.assertEqual(manifest['simulation']['history_scenario'], scenario)

    def test_history_default_false_preserves_existing_generation_contract(self):
        default = generate(self.source, self.root / 'default', days=3, orders_per_day=4)
        explicit = generate(self.source, self.root / 'explicit', days=3, orders_per_day=4, with_history=False)
        self.assertEqual(default, explicit)
        for day in range(1, 4):
            for name in FILES:
                self.assertEqual((self.root / f'default/batch-{day:03d}' / name).read_bytes(),
                                 (self.root / f'explicit/batch-{day:03d}' / name).read_bytes())
        with self.assertRaisesRegex(ValueError, 'не перезаписывается'):
            generate(self.source, self.root / 'default', with_history=True)


if __name__ == '__main__':
    unittest.main()
