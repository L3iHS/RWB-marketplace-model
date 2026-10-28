"""Новые снимки, MVCC, повторы и отказы на изолированной PostgreSQL."""
import csv
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import test_model as fixtures
from batches import FILES, fingerprint, read_manifest, seal_batch, sha256
import ingestion
import scheduler
from simulate import generate
from provenance import collect_context

ROOT = Path(__file__).resolve().parent.parent


def edit_csv(directory, table, edit):
    name = next(name for name, (t, _) in FILES.items() if t == table)
    path = directory / name
    with path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        columns = reader.fieldnames
    edit(rows)
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, columns, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


class IngestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.EdgeCases.setUpClass()
        cls.dbname = fixtures.EdgeCases.dbname
        cls.addClassCleanup(fixtures.EdgeCases.doClassCleanups)
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.source = Path(cls.directory.name) / 'source'
        cls.source.mkdir()
        with fixtures.connect(cls.dbname) as conn, conn.cursor() as cur:
            for name, (table, columns) in FILES.items():
                cur.execute('SELECT ' + ','.join(columns) + ' FROM raw.' + table)
                with (cls.source / name).open('w', encoding='utf-8', newline='') as f:
                    writer = csv.writer(f, lineterminator='\n')
                    writer.writerow(columns)
                    writer.writerows(cur.fetchall())
        # Генератор один раз на весь класс; отдельные тесты получают свои копии.
        cls.feed = Path(cls.directory.name) / 'feed'
        cls.report = generate(cls.source, cls.feed, days=5, orders_per_day=5, seed=42)

    def setUp(self):
        with fixtures.connect(self.dbname) as conn, conn.cursor() as cur:
            cur.execute('DROP SCHEMA IF EXISTS ops CASCADE')
        fixtures.build(self.dbname)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.incoming = self.root / 'incoming'
        shutil.copytree(self.feed, self.incoming)
        self.archive = self.root / 'archive'

    def batch(self, number):
        return self.incoming / f'batch-{number:03d}'

    def ingest(self, number=1):
        return ingestion.ingest(self.batch(number), self.archive, self.dbname)

    def reseal(self, number=1):
        directory = self.batch(number)
        manifest = read_manifest(directory)
        (directory / 'manifest.json').unlink()
        return seal_batch(directory, manifest['source_id'], manifest['sequence'], manifest['kind'])

    def assert_failed_unchanged(self, callback):
        before = fixtures.fingerprint(self.dbname, 'core')
        raw = fixtures.fingerprint(self.dbname, 'raw')
        current = ingestion.status(self.dbname)['current']
        result = callback()
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(fixtures.fingerprint(self.dbname, 'core'), before)
        self.assertEqual(fixtures.fingerprint(self.dbname, 'raw'), raw)
        self.assertEqual(ingestion.status(self.dbname)['current'], current)
        self.assertEqual(ingestion.status(self.dbname)['attempts'][0]['status'], 'failed')
        return result

    def test_new_snapshots_update_statuses_without_duplicates_and_preserve_raw(self):
        raw = fixtures.fingerprint(self.dbname, 'raw')
        schema = None
        for number in range(1, 6):
            result = self.ingest(number)
            self.assertEqual(result['status'], 'published', result)
            self.assertEqual(result['summary']['orders'], 4 + number * 5)
            self.assertEqual(result['summary']['new_orders'], 5)
            if number > 1:
                self.assertGreater(result['summary']['changed_statuses'], 0)
            current = ingestion.status(self.dbname)['current']
            self.assertEqual(current['kind'], 'synthetic')
            self.assertEqual(current['sequence'], number)
            self.assertTrue(Path(current['archive_path']).is_dir())
            schema = schema or current['schema_sha256']
            self.assertEqual(schema, current['schema_sha256'])
        self.assertEqual(fixtures.fingerprint(self.dbname, 'raw'), raw)
        self.assertEqual(fixtures.rows(self.dbname, 'SELECT count(*) FROM ops.dataset_versions'), [(5,)])
        self.assertGreater(fixtures.rows(self.dbname, "SELECT count(*) FROM mart.order_totals WHERE order_id LIKE 'syn_%' AND is_late")[0][0], 0)
        self.assertEqual(fixtures.rows(self.dbname, "SELECT count(*) FROM mart.order_totals WHERE order_id LIKE 'syn_%' AND payment_delta <> 0"), [(0,)])

    def test_current_repeat_skips_and_old_snapshot_does_not_roll_back(self):
        first = self.ingest(1)
        before = fixtures.fingerprint(self.dbname, 'core')
        self.assertEqual(self.ingest(1)['status'], 'skipped')
        self.assertEqual(fixtures.fingerprint(self.dbname, 'core'), before)
        second = self.ingest(2)
        self.assertEqual(self.ingest(1)['status'], 'stale_batch')
        self.assertEqual(ingestion.status(self.dbname)['current']['version_id'], second['version_id'])
        self.assertNotEqual(first['version_id'], second['version_id'])
        self.assertEqual(fixtures.rows(self.dbname, 'SELECT count(*) FROM ops.dataset_versions'), [(2,)])

    def test_checksum_failure_preserves_publication_and_can_retry_after_repair(self):
        self.ingest(1)
        path = self.batch(2) / 'olist_orders_dataset.csv'
        original = path.read_bytes()
        path.write_bytes(original + b'broken')
        self.assert_failed_unchanged(lambda: self.ingest(2))
        path.write_bytes(original)
        self.assertEqual(self.ingest(2)['status'], 'published')

    def test_missing_file_and_incomplete_history_are_rejected(self):
        self.ingest(1)
        (self.batch(2) / 'olist_sellers_dataset.csv').unlink()
        self.assert_failed_unchanged(lambda: self.ingest(2))
        edit_csv(self.batch(3), 'orders', lambda rows: rows.pop(0))
        self.reseal(3)
        result = self.assert_failed_unchanged(lambda: self.ingest(3))
        self.assertIn('полный набор истории', result['error'])

    def test_invalid_money_has_file_line_and_column(self):
        # Изменяем уже запечатанный файл и обновляем только заявленные хеши:
        # вход всё равно обязан пройти проверку значений.
        edit_csv(self.batch(1), 'order_items', lambda rows: rows[0].update(price='NaN'))
        manifest = read_manifest(self.batch(1))
        name = 'olist_order_items_dataset.csv'
        path = self.batch(1) / name
        manifest['files'][name].update(sha256=sha256(path), bytes=path.stat().st_size)
        (self.batch(1) / 'manifest.json').write_text(json.dumps(manifest))
        result = self.assert_failed_unchanged(self.ingest)
        self.assertIn(name, result['error'])
        self.assertIn('строка 2', result['error'])
        self.assertIn('price', result['error'])

    def test_foreign_key_failure_rolls_back_changes(self):
        edit_csv(self.batch(1), 'order_items', lambda rows: rows[0].update(seller_id='missing'))
        self.reseal()
        result = self.assert_failed_unchanged(self.ingest)
        self.assertIn('ForeignKeyViolation', result['error'])

    def test_failure_after_model_replacement_preserves_previous_version(self):
        self.ingest(1)
        real_check = ingestion.check_model

        def fail_after_changes(cur, statement):
            real_check(cur, statement)
            raise RuntimeError('simulated failure before commit')

        with patch.object(ingestion, 'check_model', fail_after_changes):
            self.assert_failed_unchanged(lambda: self.ingest(2))

    def test_readers_see_consistent_old_and_new_context_during_publication(self):
        first = self.ingest(1)
        reader = fixtures.connect(self.dbname)
        self.addCleanup(reader.close)
        with reader.cursor() as cur:
            cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            before = ingestion.current_version(cur)
            cur.execute('SELECT count(*) FROM core.orders')
            self.assertEqual(cur.fetchone()[0], 9)
        real_check = ingestion.check_model

        def read_while_uncommitted(cur, statement):
            with fixtures.connect(self.dbname) as other, other.cursor() as r:
                r.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                self.assertEqual(ingestion.current_version(r)['version_id'], first['version_id'])
                r.execute('SELECT count(*) FROM core.orders')
                self.assertEqual(r.fetchone()[0], 9)
            real_check(cur, statement)

        with patch.object(ingestion, 'check_model', read_while_uncommitted):
            second = self.ingest(2)
        self.assertEqual(second['status'], 'published', second)
        with reader.cursor() as cur:
            self.assertEqual(ingestion.current_version(cur), before)
            cur.execute('SELECT count(*) FROM core.orders')
            self.assertEqual(cur.fetchone()[0], 9)
        self.assertEqual(ingestion.status(self.dbname)['current']['version_id'], second['version_id'])
        self.assertEqual(fixtures.rows(self.dbname, 'SELECT count(*) FROM core.orders'), [(14,)])

    def test_concurrent_loader_returns_busy(self):
        other = fixtures.connect(self.dbname)
        self.addCleanup(other.close)
        with other.cursor() as cur:
            cur.execute('SELECT pg_advisory_lock(%s)', (ingestion.PUBLISH_LOCK,))
        self.assertEqual(self.ingest()['status'], 'busy')

    def test_acknowledgement_lost_after_commit_does_not_create_second_version(self):
        connection = fixtures.connect(self.dbname)

        class LostAcknowledgement:
            commits = 0

            def __getattr__(self, name):
                return getattr(connection, name)

            def commit(self):
                connection.commit()
                self.commits += 1
                if self.commits == 5:
                    raise OSError('simulated lost commit acknowledgement')

        with patch.object(ingestion, 'connect', return_value=LostAcknowledgement()):
            result = self.ingest()
        self.assertEqual(result['status'], 'published', result)
        self.assertTrue(result['recovered'])
        self.assertEqual(self.ingest()['status'], 'skipped')
        self.assertEqual(fixtures.rows(self.dbname, 'SELECT count(*) FROM ops.dataset_versions'), [(1,)])

    def test_abandoned_attempt_is_marked_interrupted_on_next_lock_owner(self):
        with fixtures.connect(self.dbname) as conn, conn.cursor() as cur:
            ingestion.initialize(cur)
            cur.execute("""INSERT INTO ops.ingestion_attempts
                           (attempt_id,input_path,input_signature,status)
                           VALUES ('abandoned','old','old','publishing')""")
        self.assertEqual(self.ingest()['status'], 'published')
        self.assertEqual(fixtures.rows(self.dbname, "SELECT status FROM ops.ingestion_attempts WHERE attempt_id='abandoned'"), [('failed',)])

    def test_different_source_and_unknown_old_sequence_do_not_replace_current(self):
        self.ingest(2)
        self.assertEqual(self.ingest(1)['status'], 'stale_batch')
        manifest_path = self.batch(3) / 'manifest.json'
        manifest = read_manifest(self.batch(3))
        manifest['source_id'] = 'another-source'
        manifest_path.write_text(json.dumps(manifest))
        self.assertEqual(self.ingest(3)['status'], 'stale_batch')
        self.assertEqual(ingestion.status(self.dbname)['current']['sequence'], 2)

    def test_schema_change_refuses_ingestion(self):
        self.ingest(1)
        with fixtures.connect(self.dbname) as conn, conn.cursor() as cur:
            cur.execute('ALTER TABLE core.orders ADD COLUMN probe integer')
        self.assert_failed_unchanged(lambda: self.ingest(2))

    def test_rebuild_returns_to_raw_and_clears_current_context(self):
        self.ingest()
        fixtures.build(self.dbname)
        self.assertIsNone(ingestion.status(self.dbname)['current'])
        self.assertEqual(fixtures.rows(self.dbname, 'SELECT count(*) FROM core.orders'), [(4,)])
        self.assertEqual(fixtures.rows(self.dbname, 'SELECT count(*) FROM ops.dataset_versions'), [(1,)])

    def test_export_context_includes_publication_in_same_transaction(self):
        result = self.ingest()
        with fixtures.connect(self.dbname) as conn:
            context = collect_context(conn, ROOT)
        self.assertEqual(context['publication']['version_id'], result['version_id'])
        self.assertEqual(context['publication']['kind'], 'synthetic')

    def test_scheduler_processes_one_batch_per_cycle_then_idles(self):
        for index in range(1, 6):
            result = scheduler.tick(self.incoming, self.archive, self.dbname)
            self.assertEqual(result['status'], 'published', result)
            self.assertEqual(ingestion.status(self.dbname)['current']['sequence'], index)
        self.assertEqual(scheduler.tick(self.incoming, self.archive, self.dbname)['status'], 'idle')

    def test_scheduler_records_failure_without_busy_retry_and_continues_next_snapshot(self):
        (self.batch(1) / 'olist_sellers_dataset.csv').unlink()
        self.assertEqual(scheduler.tick(self.incoming, self.archive, self.dbname)['status'], 'failed')
        self.assertEqual(scheduler.tick(self.incoming, self.archive, self.dbname)['status'], 'published')
        self.assertEqual(ingestion.status(self.dbname)['current']['sequence'], 2)

    def test_generator_is_reproducible_and_does_not_overwrite(self):
        duplicate = self.root / 'duplicate'
        report = generate(self.source, duplicate, days=5, orders_per_day=5, seed=42)
        self.assertEqual(report, self.report)
        for number in range(1, 6):
            self.assertEqual(fingerprint(read_manifest(duplicate / f'batch-{number:03d}')),
                             fingerprint(read_manifest(self.batch(number))))
        with self.assertRaises(ValueError):
            generate(self.source, duplicate)

    def test_crlf_source_with_multiline_review_remains_loadable(self):
        source = self.root / 'crlf-source'
        shutil.copytree(self.source, source)
        name = 'olist_order_reviews_dataset.csv'
        with (source / name).open(encoding='utf-8', newline='') as f:
            values = list(csv.reader(f))
        message = values[0].index('review_comment_message')
        values[1][message] = 'первая\r\nвторая'
        with (source / name).open('w', encoding='utf-8', newline='') as f:
            csv.writer(f, lineterminator='\r\n').writerows(values)
        output = self.root / 'crlf-feed'
        generate(source, output, days=1, orders_per_day=5)
        result = ingestion.ingest(output / 'batch-001', self.archive, self.dbname)
        self.assertEqual(result['status'], 'published', result)
        self.assertEqual(fixtures.rows(self.dbname, "SELECT comment_message FROM core.order_reviews WHERE review_id='r1' AND order_id='o1'"), [('первая\r\nвторая',)])

    def test_duplicate_key_and_extra_file_are_rejected(self):
        edit_csv(self.batch(1), 'orders', lambda rows: rows.append(rows[0]))
        with self.assertRaisesRegex(ValueError, 'повтор ключа'):
            self.reseal()
        (self.batch(2) / 'extra.csv').write_text('extra')
        self.assert_failed_unchanged(lambda: self.ingest(2))


class SchedulerLifecycleTests(unittest.TestCase):
    def test_bounded_worker_waits_between_cycles_and_exits(self):
        from threading import Event
        stop = Event()
        with patch.object(scheduler, 'tick', return_value=dict(status='idle')) as tick, \
                patch.object(stop, 'wait', return_value=False) as wait, redirect_stdout(io.StringIO()):
            self.assertEqual(scheduler.run('incoming', 'archive', 60, 3, stop=stop), 0)
        self.assertEqual(tick.call_count, 3)
        self.assertEqual(wait.call_count, 2)

    def test_one_shot_failure_has_nonzero_exit(self):
        with patch.object(scheduler, 'tick', return_value=dict(status='failed')), redirect_stdout(io.StringIO()):
            self.assertEqual(scheduler.run('incoming', 'archive', 60, 1), 1)

    def test_invalid_interval_is_rejected(self):
        for value in (0, -1, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                scheduler.run('incoming', 'archive', value, 1)


if __name__ == '__main__':
    unittest.main()
