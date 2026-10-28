"""Загрузка проверяется настоящим HTTP-сервером в loopback, без внешней сети."""
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run as runner


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data = Path(self.directory.name)
        self.name = 'olist_orders_dataset.csv'
        self.good = b'order_id,customer_id\no1,c1\n'
        self.payload = self.good
        self.interrupted = False
        self.calls = 0
        case = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                case.calls += 1
                self.send_response(200)
                self.send_header('Content-Length', len(case.payload) + (100 if case.interrupted else 0))
                self.end_headers()
                self.wfile.write(case.payload)
                self.close_connection = True

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        worker.start()

        def stop():
            server.shutdown()
            server.server_close()
            worker.join()

        self.addCleanup(stop)
        for name, value in (
            ('DATA_DIR', self.data), ('DATA_FILES', [self.name]),
            ('DATA_URL', f'http://127.0.0.1:{server.server_port}/'),
            ('DATA_SHA256', {self.name: hashlib.sha256(self.good).hexdigest()}),
        ):
            replacement = patch.object(runner, name, value, create=True)
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_corrupt_existing_file_is_replaced_with_verified_download(self):
        (self.data / self.name).write_bytes(b'incomplete file')
        runner.download_data()
        self.assertEqual((self.data / self.name).read_bytes(), self.good)
        self.assertEqual(self.calls, 1)

    def test_checksum_mismatch_is_not_published(self):
        self.payload = b'wrong data'
        with self.assertRaises(ValueError):
            runner.download_data()
        self.assertFalse((self.data / self.name).exists())
        self.assertEqual(list(self.data.iterdir()), [])

    def test_interrupted_download_is_cleaned_and_retry_succeeds(self):
        self.payload = self.good[:8]
        self.interrupted = True
        with self.assertRaises((ValueError, urllib.error.URLError, http.client.HTTPException)):
            runner.download_data()
        self.assertFalse((self.data / self.name).exists())
        self.assertEqual(list(self.data.iterdir()), [], 'После сбоя остался частичный файл')
        self.payload, self.interrupted = self.good, False
        runner.download_data()
        self.assertEqual((self.data / self.name).read_bytes(), self.good)

    def test_verified_existing_file_does_not_use_network(self):
        (self.data / self.name).write_bytes(self.good)
        runner.download_data()
        self.assertEqual(self.calls, 0)


class SourceRevisionTests(unittest.TestCase):
    def test_download_source_is_pinned(self):
        self.assertIn('/d9e49802f3e92d09ee94ab9ccc5e457f207a8959/', runner.DATA_URL)


if __name__ == '__main__':
    unittest.main()
