"""Кэш HTTP-ответов: границы, актуальность и одновременные запросы."""
from concurrent.futures import ThreadPoolExecutor
import importlib
from threading import Barrier, Event
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.cache import DashboardCache
import test_model as fixtures

api = importlib.import_module('backend.app')


class DashboardCacheTests(unittest.TestCase):
    def test_lru_capacity_and_ttl_are_enforced(self):
        now = [0.0]
        cache = DashboardCache(max_entries=2, ttl_seconds=60, clock=lambda: now[0])
        compute = Mock(side_effect=lambda: object())
        first = cache.get_or_compute('a', compute)
        cache.get_or_compute('b', compute)
        self.assertIs(cache.get_or_compute('a', compute), first)
        cache.get_or_compute('c', compute)
        self.assertIs(cache.get_or_compute('a', compute), first)
        cache.get_or_compute('b', compute)
        self.assertEqual(compute.call_count, 4)
        now[0] = 59.0
        self.assertIs(cache.get_or_compute('a', compute), first)
        now[0] = 60.0
        self.assertIsNot(cache.get_or_compute('a', compute), first)
        self.assertEqual(compute.call_count, 5)

    def test_each_cache_identity_change_causes_a_miss(self):
        cache = DashboardCache()
        compute = Mock(return_value={'orders': 4})
        base = ('database', 42, '100:100:', 'version-one', 'original', None, None, None)
        keys = [base]
        for index, value in enumerate(('another-db', 43, '101:101:', 'version-two',
                                       'demo', '2017-01-01', '2017-03-01', 'SP')):
            changed = list(base)
            changed[index] = value
            keys.append(tuple(changed))
        for database, oid, token, version, dataset, start, end, state in keys:
            cursor = Mock()
            cursor.fetchone.side_effect = [(database, oid, token, 'ops.current_dataset'), (version,)]
            params = api.parse_filters(start, end, state)
            key = api.dashboard_cache_key(cursor, dataset, params)
            cache.get_or_compute(key, compute)
            cache.get_or_compute(key, compute)
        self.assertEqual(compute.call_count, len(keys))

    def test_concurrent_requests_compute_only_once(self):
        cache = DashboardCache()
        barrier = Barrier(8)
        started, release = Event(), Event()
        result = {'revenue': '10.00'}

        def compute():
            started.set()
            if not release.wait(5):
                raise AssertionError('Вычисление не освобождено')
            return result

        compute_once = Mock(side_effect=compute)

        def request():
            barrier.wait(timeout=5)
            return cache.get_or_compute('same', compute_once)

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(request) for _ in range(8)]
            try:
                self.assertTrue(started.wait(5))
            finally:
                release.set()
            self.assertTrue(all(future.result(timeout=5) is result for future in futures))
        self.assertEqual(compute_once.call_count, 1)

    def test_exception_is_not_cached_and_next_request_retries(self):
        cache = DashboardCache()
        compute = Mock(side_effect=[RuntimeError('temporary'), {'orders': 4}])
        with self.assertRaisesRegex(RuntimeError, 'temporary'):
            cache.get_or_compute('same', compute)
        self.assertEqual(cache.get_or_compute('same', compute), {'orders': 4})
        self.assertEqual(cache.get_or_compute('same', compute), {'orders': 4})
        self.assertEqual(compute.call_count, 2)


class DashboardCacheRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.EdgeCases.setUpClass()
        cls.dbname = fixtures.EdgeCases.dbname
        cls.addClassCleanup(fixtures.EdgeCases.doClassCleanups)

    def setUp(self):
        self.execute('DROP SCHEMA IF EXISTS ops CASCADE')
        fixtures.build(self.dbname)
        connection = patch.object(api, 'connect_database', lambda *args: fixtures.connect(self.dbname))
        connection.start()
        self.addCleanup(connection.stop)
        cache = patch.object(api, 'dashboard_cache', DashboardCache())
        cache.start()
        self.addCleanup(cache.stop)
        self.client = TestClient(api.app)
        self.addCleanup(self.client.close)

    def execute(self, statement, params=None):
        with fixtures.connect(self.dbname) as conn, conn.cursor() as cur:
            cur.execute(statement, params)

    def dashboard(self, **params):
        response = self.client.get('/api/dashboard', params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_repeated_normalized_filters_hit_without_recomputing(self):
        with patch.object(api, 'dashboard_data', wraps=api.dashboard_data) as compute:
            first = self.dashboard(state=' sp ')
            second = self.dashboard(state='SP')
        self.assertEqual(first, second)
        self.assertEqual(compute.call_count, 1)
        self.assertEqual(first['summary']['revenue_brl'], '45.00')

    def test_different_filters_and_dataset_do_not_share_results(self):
        with patch.object(api, 'dashboard_data', wraps=api.dashboard_data) as compute:
            sp = self.dashboard(state='SP')
            rj = self.dashboard(state='RJ')
            self.dashboard(state='SP', dataset='demo')
        self.assertEqual(compute.call_count, 3)
        self.assertEqual(sp['summary']['revenue_brl'], '45.00')
        self.assertEqual(rj['summary']['revenue_brl'], '30.00')

    def test_publication_version_change_invalidates_cached_response(self):
        self.execute((fixtures.ROOT / 'scripts/sql/ingestion.sql').read_text())
        self.execute("""INSERT INTO ops.dataset_versions
            (version_id,dataset_sha256,transform_sha256,schema_sha256,source_id,sequence,
             kind,archive_path,manifest,summary)
            VALUES ('version-one','hash','transform','schema','cache-test',1,
                    'synthetic','test','{}','{}');
            INSERT INTO ops.current_dataset(singleton,version_id) VALUES (true,'version-one')""")
        with patch.object(api, 'dashboard_data', wraps=api.dashboard_data) as compute:
            first = self.dashboard()
            self.execute("""INSERT INTO ops.dataset_versions
                (version_id,dataset_sha256,transform_sha256,schema_sha256,source_id,sequence,
                 kind,archive_path,manifest,summary)
                VALUES ('version-two','new-hash','transform','schema','cache-test',2,
                        'synthetic','test','{}','{}');
                UPDATE ops.current_dataset SET version_id='version-two'""")
            second = self.dashboard()
        self.assertEqual(compute.call_count, 2)
        self.assertEqual(first['context']['dataset_version'], 'version-one')
        self.assertEqual(second['context']['dataset_version'], 'version-two')

    def test_rebuilt_orders_oid_invalidates_original_response(self):
        with api.snapshot() as cur:
            before = api.dashboard_cache_key(cur, 'original', api.parse_filters())
        with patch.object(api, 'dashboard_data', wraps=api.dashboard_data) as compute:
            self.dashboard()
            fixtures.build(self.dbname)
            self.dashboard()
        with api.snapshot() as cur:
            after = api.dashboard_cache_key(cur, 'original', api.parse_filters())
        self.assertEqual(compute.call_count, 2)
        self.assertNotEqual(before[1], after[1])

    def test_direct_write_changes_snapshot_token_and_invalidates_response(self):
        with api.snapshot() as cur:
            before = api.dashboard_cache_key(cur, 'original', api.parse_filters())
        with patch.object(api, 'dashboard_data', wraps=api.dashboard_data) as compute:
            first = self.dashboard()
            self.execute("UPDATE core.order_items SET price=20 WHERE order_id='o1' AND order_item_id=1")
            second = self.dashboard()
        with api.snapshot() as cur:
            after = api.dashboard_cache_key(cur, 'original', api.parse_filters())
        self.assertEqual(compute.call_count, 2)
        self.assertEqual(before[1], after[1])
        self.assertNotEqual(before[2], after[2])
        self.assertEqual(first['summary']['revenue_brl'], '75.00')
        self.assertEqual(second['summary']['revenue_brl'], '85.00')


if __name__ == '__main__':
    unittest.main()
