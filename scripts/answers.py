"""Показывает ответы на вопросы 1–5 и сохраняет их в CSV и JSON (artifacts/answers/).

Только чтение модели. Запуск: docker compose run --rm app answers
"""
import csv
import json
from pathlib import Path

import pandas as pd

from db import connect

ROOT = Path(__file__).resolve().parent.parent


def question_title(sql_text, fallback):
    """Заголовок вопроса — первая строка комментария в начале SQL-файла."""
    first = sql_text.lstrip().splitlines()[0]
    return first.lstrip('- ').strip() if first.startswith('--') else fallback


def main():
    output = ROOT / 'artifacts' / 'answers'
    output.mkdir(parents=True, exist_ok=True)
    pd.set_option('display.max_rows', None)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)

    report = {}
    with connect() as conn, conn.cursor() as cur:
        # Все запросы видят один и тот же снимок данных и ничего не меняют.
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        for path in sorted((ROOT / 'answers').glob('0[1-5]_*.sql')):
            sql_text = path.read_text(encoding='utf-8')
            cur.execute(sql_text)
            names = [c.name for c in cur.description]
            result = cur.fetchall()

            print(f'\n=== {question_title(sql_text, path.stem)}')
            print(pd.DataFrame(result, columns=names).to_string(index=False))

            with (output / (path.stem + '.csv')).open('w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(names)
                writer.writerows(result)
            report[path.stem] = [dict(zip(names, row)) for row in result]

    (output / 'results.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n')
    print(f'\nОтветы сохранены в {output.relative_to(ROOT)}/ (CSV и results.json)')


if __name__ == '__main__':
    main()
