"""Отказы SQL и файловой публикации на отдельной PostgreSQL и временном каталоге."""
import hashlib
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import psycopg2

import test_model as fixtures

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import answers as exporter

ROOT = Path(__file__).resolve().parent.parent


def file_hashes(path):
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob('*') if p.is_file()}


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.EdgeCases.setUpClass()
        cls.dbname = fixtures.EdgeCases.dbname
        cls.addClassCleanup(fixtures.EdgeCases.doClassCleanups)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        shutil.copytree(ROOT / 'answers', self.root / 'answers')
        shutil.copytree(ROOT / 'model', self.root / 'model')
        self.output = self.root / 'artifacts' / 'answers'
        self.output.mkdir(parents=True)

    def export(self):
        output = io.StringIO()
        with patch.object(exporter, 'ROOT', self.root), \
                patch.object(exporter, 'connect', lambda: fixtures.connect(self.dbname)), \
                patch.object(sys, 'argv', ['answers.py', '--output-dir', str(self.output)]), redirect_stdout(output):
            exporter.main()
        return output.getvalue()

    def test_console_shows_published_answers(self):
        output = self.export()
        self.current()
        self.assertIn('Вопрос 3. Средний чек заказа.', output)
        self.assertIn('27.33', output)
        self.assertIn('Опубликован полный комплект:', output)

    def answer_files(self):
        """Файлы ответов во временной копии: все вопросы 01–10, без 99_controls."""
        with patch.object(exporter, 'ROOT', self.root):
            return exporter.answer_files()

    def current(self):
        pointer = self.output / 'current.json'
        self.assertTrue(pointer.is_file(), 'Нет атомарного указателя на полный результат')
        current = json.loads(pointer.read_text())
        generation = self.output / current['generation']
        manifest_path = generation / 'manifest.json'
        self.assertEqual(hashlib.sha256(manifest_path.read_bytes()).hexdigest(), current['manifest_sha256'])
        return current, generation, json.loads(manifest_path.read_text())

    def test_failed_query_does_not_replace_existing_files(self):
        for p in self.answer_files():
            (self.output / (p.stem + '.csv')).write_text('previous result\n')
        (self.output / 'results.json').write_text('{"previous":true}')
        before = file_hashes(self.output)
        (self.root / 'answers/02_top_sellers.sql').write_text('SELECT 1/0 AS broken')
        with self.assertRaises(psycopg2.Error):
            self.export()
        self.assertEqual(file_hashes(self.output), before)

    def test_manifest_describes_complete_files_and_database_context(self):
        self.export()
        _, generation, manifest = self.current()
        self.assertEqual(manifest['format_version'], 1)
        self.assertEqual(sorted(manifest['queries']), [p.name for p in self.answer_files()])
        for name, info in manifest['files'].items():
            self.assertEqual(hashlib.sha256((generation / name).read_bytes()).hexdigest(), info['sha256'])
        self.assertEqual(set(manifest['context']), {'raw', 'core', 'model_schema_sha256', 'workspace_model_sha256'})
        for schema in ('raw', 'core'):
            self.assertEqual(len(manifest['context'][schema]['sha256']), 64)
            self.assertTrue(manifest['context'][schema]['tables'])
        for name, query in manifest['queries'].items():
            self.assertEqual(query['sql'], (self.root / 'answers' / name).read_text())
            self.assertEqual(hashlib.sha256(query['sql'].encode()).hexdigest(), query['sha256'])

    def test_new_export_keeps_previous_generation(self):
        self.export()
        first, generation, _ = self.current()
        before = file_hashes(generation)
        self.export()
        second, _, _ = self.current()
        self.assertNotEqual(first['generation'], second['generation'])
        self.assertEqual(file_hashes(generation), before)

    def test_pointer_failure_keeps_previous_generation(self):
        self.export()
        _, generation, _ = self.current()
        before = (self.output / 'current.json').read_bytes()
        files = file_hashes(generation)
        real_replace = os.replace

        def fail_pointer(source, target):
            if Path(target) == self.output / 'current.json':
                raise OSError('simulated pointer failure')
            return real_replace(source, target)

        with patch.object(exporter.os, 'replace', side_effect=fail_pointer):
            with self.assertRaises(OSError):
                self.export()
        self.assertEqual((self.output / 'current.json').read_bytes(), before)
        self.assertEqual(file_hashes(generation), files)
        self.assertFalse(list(self.output.glob('.pending-*')))

    def test_sql_failure_keeps_published_generation(self):
        self.export()
        _, generation, _ = self.current()
        before = (self.output / 'current.json').read_bytes()
        files = file_hashes(generation)
        (self.root / 'answers/02_top_sellers.sql').write_text('SELECT 1/0 AS broken')
        with self.assertRaises(psycopg2.Error):
            self.export()
        self.assertEqual((self.output / 'current.json').read_bytes(), before)
        self.assertEqual(file_hashes(generation), files)
        self.assertFalse(list(self.output.glob('.pending-*')))

    def test_file_write_failure_keeps_published_generation(self):
        self.export()
        _, generation, _ = self.current()
        before = (self.output / 'current.json').read_bytes()
        files = file_hashes(generation)
        with patch.object(exporter.json, 'dump', side_effect=OSError('simulated write failure')):
            with self.assertRaises(OSError):
                self.export()
        self.assertEqual((self.output / 'current.json').read_bytes(), before)
        self.assertEqual(file_hashes(generation), files)
        self.assertFalse(list(self.output.glob('.pending-*')))

    def test_missing_answer_refuses_partial_export(self):
        for name in ('04_repeat_customers.sql', '07_delivery_by_state.sql'):
            with self.subTest(missing=name):
                path = self.root / 'answers' / name
                sql_text = path.read_text()
                path.unlink()
                try:
                    with self.assertRaises(ValueError):
                        self.export()
                    self.assertEqual(list(self.output.iterdir()), [])
                finally:
                    path.write_text(sql_text)

    def test_all_questions_exported(self):
        output = self.export()
        _, _, manifest = self.current()
        self.assertEqual({name[:2] for name in manifest['queries']}, exporter.QUESTIONS)
        self.assertIn('Вопрос 10. Связь оценки покупателя со сроком доставки.', output)

    def test_workspace_sql_is_not_claimed_as_applied_model_revision(self):
        self.export()
        _, _, first = self.current()
        with (self.root / 'model/03_marts.sql').open('a') as f:
            f.write('\n-- Unapplied workspace change\n')
        self.export()
        _, _, second = self.current()
        self.assertEqual(first['context']['model_schema_sha256'], second['context']['model_schema_sha256'])
        self.assertNotEqual(first['context']['workspace_model_sha256'], second['context']['workspace_model_sha256'])

    def test_context_identifies_actual_model_data(self):
        self.export()
        _, _, first = self.current()
        try:
            with fixtures.connect(self.dbname) as conn, conn.cursor() as cur:
                cur.execute("UPDATE core.order_items SET price = price + 1 WHERE order_id='o1' AND order_item_id=1")
            self.export()
            _, _, second = self.current()
            self.assertEqual(first['context']['raw'], second['context']['raw'])
            self.assertNotEqual(first['context']['core']['sha256'], second['context']['core']['sha256'])
            self.assertEqual(first['context']['model_schema_sha256'], second['context']['model_schema_sha256'])
        finally:
            fixtures.build(self.dbname)

    def test_model_revision_tracks_type_precision(self):
        try:
            with fixtures.connect(self.dbname) as conn, conn.cursor() as cur:
                cur.execute('CREATE TABLE core.revision_probe (value numeric(12,2))')
            self.export()
            _, _, first = self.current()
            with fixtures.connect(self.dbname) as conn, conn.cursor() as cur:
                cur.execute('ALTER TABLE core.revision_probe ALTER COLUMN value TYPE numeric(18,2)')
            self.export()
            _, _, second = self.current()
            self.assertEqual(first['context']['core'], second['context']['core'])
            self.assertNotEqual(first['context']['model_schema_sha256'], second['context']['model_schema_sha256'])
        finally:
            with fixtures.connect(self.dbname) as conn, conn.cursor() as cur:
                cur.execute('DROP TABLE IF EXISTS core.revision_probe')


if __name__ == '__main__':
    unittest.main()
