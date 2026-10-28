#!/usr/bin/env python3
"""Сохранить ответы из модели в CSV: .venv/bin/python scripts/export_answers.py."""
import argparse
import csv
from pathlib import Path
import psycopg2

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn', default='postgresql://hack:hack@localhost:5432/marketplace')
    parser.add_argument('--output', type=Path, default=ROOT / 'model/results')
    args = parser.parse_args()
    # Сначала выполнить все запросы в едином снимке, затем записать результаты.
    results = []
    with psycopg2.connect(args.dsn) as conn:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor() as cur:
            for query in sorted((ROOT / 'model/queries').glob('*.sql')):
                cur.execute(query.read_text(encoding='utf-8'))
                results.append((query.stem, [c.name for c in cur.description], cur.fetchall()))
    args.output.mkdir(parents=True, exist_ok=True)
    for name, columns, rows in results:
        path = args.output / f'{name}.csv'
        with path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(columns)
            writer.writerows(rows)
        print(f'{path.name}: {len(rows)} строк')


if __name__ == '__main__':
    main()
