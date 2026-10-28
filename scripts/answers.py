"""Выгружает ответы на вопросы 1–5 в CSV и JSON (artifacts/answers/); только чтение модели.

Запуск: make answers   (или .venv/bin/python scripts/answers.py)
"""
import csv
import json
from pathlib import Path

from db import connect

ROOT = Path(__file__).resolve().parent.parent


def main():
    output = ROOT / 'artifacts' / 'answers'
    output.mkdir(parents=True, exist_ok=True)
    report = {}
    with connect() as conn, conn.cursor() as cur:
        # Все запросы видят один и тот же снимок данных и ничего не меняют.
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        for path in sorted((ROOT / 'answers').glob('0[1-5]_*.sql')):
            cur.execute(path.read_text())
            names = [c.name for c in cur.description]
            result = cur.fetchall()
            with (output / (path.stem + '.csv')).open('w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(names)
                writer.writerows(result)
            report[path.stem] = [dict(zip(names, row)) for row in result]
            print(f'{path.stem}: {len(result)} строк')
    (output / 'results.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n')


if __name__ == '__main__':
    main()
