"""Публикует неизменяемый комплект ответов 1–5 и показывает его в терминале.

Запуск: docker compose run --rm app answers
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

import pandas as pd

from db import connect
from provenance import collect_context

ROOT = Path(__file__).resolve().parent.parent


def write_json(path, value):
    with path.open('w', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, default=str, allow_nan=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())


def file_info(path):
    return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}


def question_title(sql_text, fallback):
    """Заголовок берётся из выполненного SQL, сохранённого в manifest."""
    lines = sql_text.lstrip().splitlines()
    return lines[0][2:].strip() if lines and lines[0].startswith('--') else fallback


def show_answers(generation):
    """Экран и файлы используют один опубликованный снимок, без повторного SQL."""
    manifest = json.loads((generation / 'manifest.json').read_text(encoding='utf-8'))
    report = json.loads((generation / 'results.json').read_text(encoding='utf-8'))
    for name, query in manifest['queries'].items():
        columns = [column['name'] for column in query['columns']]
        print(f'\n=== {question_title(query["sql"], Path(name).stem)}')
        print(pd.DataFrame(report[Path(name).stem], columns=columns).to_string(index=False))


def export_answers(output):
    queries = sorted((ROOT / 'answers').glob('0[1-5]_*.sql'))
    if len(queries) != 5 or {p.name[:2] for p in queries} != {'01', '02', '03', '04', '05'}:
        raise ValueError('Для полного комплекта нужны ровно пять SQL-ответов 01–05')
    # SQL фиксируется до выполнения: правка файла во время запроса не подменит сохранённый текст.
    statements = [(p.name, p.read_text(encoding='utf-8')) for p in queries]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    export_id = uuid.uuid4().hex
    pointer_tmp = output / f'.current-{export_id}.json'
    try:
        with tempfile.TemporaryDirectory(prefix='.pending-', dir=output) as directory:
            stage = Path(directory)
            (stage / 'sql').mkdir()
            report, metadata = {}, {}
            with connect() as conn, conn.cursor() as cur:
                cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                cur.execute("SET LOCAL TIME ZONE 'UTC'")
                cur.execute("SET LOCAL datestyle = 'ISO, YMD'")
                cur.execute('SET LOCAL search_path = pg_catalog')
                context = collect_context(conn, ROOT)
                for name, statement in statements:
                    cur.execute(statement)
                    columns = [c.name for c in cur.description]
                    rows = cur.fetchall()
                    stem = Path(name).stem
                    with (stage / (stem + '.csv')).open('w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f, lineterminator='\n')
                        writer.writerow(columns)
                        writer.writerows(rows)
                        f.flush()
                        os.fsync(f.fileno())
                    with (stage / 'sql' / name).open('w', encoding='utf-8', newline='\n') as f:
                        f.write(statement)
                        f.flush()
                        os.fsync(f.fileno())
                    report[stem] = [dict(zip(columns, row)) for row in rows]
                    metadata[name] = {
                        'sql': statement, 'sha256': hashlib.sha256(statement.encode('utf-8')).hexdigest(),
                        'rows': len(rows), 'columns': [dict(name=c.name, type_code=c.type_code) for c in cur.description],
                    }
            write_json(stage / 'results.json', report)
            manifest = {
                'format_version': 1, 'export_id': export_id,
                'created_at': datetime.now(timezone.utc).isoformat(), 'context': context, 'queries': metadata,
                'files': {p.relative_to(stage).as_posix(): file_info(p)
                          for p in sorted(stage.rglob('*')) if p.is_file()},
            }
            write_json(stage / 'manifest.json', manifest)
            generations = output / 'generations'
            generations.mkdir(exist_ok=True)
            destination = generations / export_id
            os.replace(stage, destination)
            write_json(pointer_tmp, {
                'format_version': 1, 'generation': f'generations/{export_id}',
                'manifest_sha256': file_info(destination / 'manifest.json')['sha256'],
            })
            # Единственная точка публикации. До неё прежний current.json не меняется.
            os.replace(pointer_tmp, output / 'current.json')
    finally:
        pointer_tmp.unlink(missing_ok=True)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, help='каталог поколений результатов')
    args = parser.parse_args()
    output = args.output_dir or ROOT / 'artifacts' / 'runtime' / 'answers'
    destination = export_answers(output)
    show_answers(destination)
    print(f'Опубликован полный комплект: {destination}')
    print(f'Указатель: {Path(output) / "current.json"}')


if __name__ == '__main__':
    main()
