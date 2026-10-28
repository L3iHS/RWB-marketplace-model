"""Необязательный worker: один готовый полный снимок за цикл, без фоновой установки."""
import json
import math
from pathlib import Path
import signal
import threading

from batches import read_manifest
from db import connect
from ingestion import ingest, input_signature


def candidates(incoming, dbname=None):
    incoming = Path(incoming)
    if not incoming.is_dir():
        raise ValueError(f'Нет входного каталога: {incoming}')
    with connect(dbname) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('ops.ingestion_attempts')")
        completed = set()
        if cur.fetchone()[0]:
            cur.execute('SELECT input_path,input_signature FROM ops.ingestion_attempts WHERE finished_at IS NOT NULL')
            completed = set(cur.fetchall())
    ready = []
    for directory in incoming.iterdir():
        if directory.name.startswith('.') or not directory.is_dir() or not (directory / 'manifest.json').is_file():
            continue
        if (str(directory.resolve()), input_signature(directory)) in completed:
            continue
        try:
            manifest = read_manifest(directory)
            order = (manifest['source_id'], manifest['sequence'], directory.name)
        except (ValueError, TypeError, KeyError):
            # Неверный manifest тоже проходит через ingest и получает запись failed.
            order = ('', 0, directory.name)
        ready.append((order, directory))
    return [directory for _, directory in sorted(ready)]


def tick(incoming, archive_root, dbname=None):
    pending = candidates(incoming, dbname)
    return ingest(pending[0], archive_root, dbname) if pending else dict(status='idle')


def run(incoming, archive_root, interval_seconds=86400, max_runs=None, dbname=None, stop=None):
    if not math.isfinite(interval_seconds) or interval_seconds <= 0 or max_runs is not None and max_runs < 1:
        raise ValueError('Интервал и число запусков должны быть положительными')
    stop = stop or threading.Event()
    runs, failures = 0, 0
    while not stop.is_set():
        try:
            result = tick(incoming, archive_root, dbname)
        except Exception as error:
            result = dict(status='failed', error=f'{type(error).__name__}: {error}')
        print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
        failures += result['status'] not in {'published', 'skipped', 'idle'}
        runs += 1
        if max_runs is not None and runs >= max_runs:
            break
        stop.wait(interval_seconds)
    return 1 if failures else 0


def serve(incoming, archive_root, interval_seconds, max_runs=None):
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    return run(incoming, archive_root, interval_seconds, max_runs, stop=stop)
