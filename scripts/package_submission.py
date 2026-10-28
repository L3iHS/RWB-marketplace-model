#!/usr/bin/env python3
"""Проверить текущие ответы и собрать dist/capibara-submission.zip.
Рабочую базу только читает; --verify-clean использует временную базу. CSV, .venv и настройки приложений в архив не входят.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import time
import uuid
import zipfile

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn
from build_model import ROOT, read_build_sql
from check_model import check_answers
from load_raw import DATA_DIR, INIT_DIR, MAPPING, load_file, run_sql_file

REQUIRED = [
    'model/build.sql', 'model/000_validate_raw.sql', 'model/001_schema.sql',
    'model/002_load.sql', 'model/003_marts.sql', 'model/004_checks.sql',
    'model/005_comments.sql', 'model/START_HERE.md', 'model/team_walkthrough.sql',
    'model/submission/INDEX.md', 'model/submission/decisions.md',
    'model/submission/dashboard.md', 'model/submission/roadmap.md',
    'model/submission/ai_usage.md', 'model/submission/defense.md',
    'model/submission/checkpoint_1.md', 'notebooks/01_data_investigation.ipynb',
    'notebooks/01_data_investigation.html', 'requirements-notebook.txt',
]



def verify_clean_sql(dsn, standalone):
    """Проверить собранный SQL на свежем raw, без предварительного ANALYZE."""
    missing = [name for name, _, _ in MAPPING if not (DATA_DIR / name).is_file()]
    if missing:
        raise ValueError('Для --verify-clean нужны исходные CSV: ' + ', '.join(missing))
    name = 'hack_submission_' + uuid.uuid4().hex[:12]
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    conn = None
    created = False
    try:
        with admin.cursor() as cur:
            cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        created = True
        conn = psycopg2.connect(make_dsn(dsn, dbname=name))
        with conn.cursor() as cur:
            cur.execute('CREATE SCHEMA raw')
            run_sql_file(cur, INIT_DIR / '02_raw_ddl.sql')
            for filename, table, columns in MAPPING:
                load_file(cur, DATA_DIR / filename, table, columns)
        conn.commit()
        # Ограничение времени — защита регрессионной проверки от зависания,
        # не обещание продуктового SLA. Рабочая база не затрагивается.
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '90s'")
            started = time.monotonic()
            cur.execute(standalone)
            seconds = time.monotonic() - started
            check_answers(cur)
        return {'passed': True, 'build_seconds': round(seconds, 3),
                'block_a_controls': 'passed', 'raw_preanalyzed': False}
    finally:
        if conn is not None:
            conn.close()
        try:
            if created:
                with admin.cursor() as cur:
                    cur.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        finally:
            admin.close()



def validate_notebook(notebook_path, html_path):
    """Не требует Jupyter: проверяет сохранённое исполнение и актуальность источника.

    Это контроль артефактов, не новая попытка выполнить исследование и не
    криптографическое доказательство происхождения вручную редактируемого файла.
    """
    notebook = json.loads(notebook_path.read_text(encoding='utf-8'))
    code_cells = [cell for cell in notebook['cells'] if cell['cell_type']=='code']
    if not code_cells or any(cell.get('execution_count') is None for cell in code_cells):
        raise ValueError('Не все ячейки notebook выполнены: запустите scripts/run_notebook.py')
    if any(output.get('output_type')=='error' for cell in code_cells for output in cell.get('outputs', [])):
        raise ValueError('Notebook содержит ошибки исполнения')
    sources = [cell['source'] if isinstance(cell['source'],str) else ''.join(cell['source']) for cell in notebook['cells']]
    source_hash = hashlib.sha256(json.dumps(sources,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()
    if notebook.get('metadata',{}).get('capibara',{}).get('executed_source_sha256') != source_hash:
        raise ValueError('Notebook изменён после выполнения: запустите scripts/run_notebook.py')
    if f'<!-- capibara-source-sha256: {source_hash} -->' not in html_path.read_text(encoding='utf-8'):
        raise ValueError('HTML не соответствует notebook: запустите scripts/run_notebook.py')
    return {'executed_code_cells':len(code_cells),'errors':0,
            'source_sha256':source_hash,'html_matches_source':True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn', default='postgresql://hack:hack@localhost:5432/marketplace')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--verify-clean', action='store_true', help='Проверить единый SQL на временной чистой базе; нужны CSV и право CREATEDB')
    args = parser.parse_args()
    for name in REQUIRED:
        if not (ROOT / name).is_file():
            parser.error(f'Отсутствует файл комплекта: {name}')
    task_ids = {int(n) for n in re.findall(r'^###\s+(\d+)\.', (ROOT / 'docs/tasks.md').read_text(encoding='utf-8'), re.M)}
    queries = sorted((ROOT / 'model/queries').glob('*.sql'))
    query_ids = {int(p.name.split('_')[0]) for p in queries}
    if task_ids != query_ids:
        parser.error(f'Номера вопросов и ответов различаются: задания={sorted(task_ids)}, ответы={sorted(query_ids)}')

    try:
        notebook_check = validate_notebook(ROOT/'notebooks/01_data_investigation.ipynb', ROOT/'notebooks/01_data_investigation.html')
    except ValueError as error:
        parser.error(str(error))
    checks = {'available_questions': sorted(task_ids), 'answers': {}, 'notebook': notebook_check}
    with psycopg2.connect(args.dsn) as conn:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor() as cur:
            check_answers(cur)
            checks['block_a_controls'] = 'passed'
            for path in queries:
                cur.execute(path.read_text(encoding='utf-8'))
                rows = cur.fetchall()
                stream = io.StringIO(newline='')
                writer = csv.writer(stream)
                writer.writerow([c.name for c in cur.description])
                writer.writerows(rows)
                saved = ROOT / 'model/results' / f'{path.stem}.csv'
                if not saved.exists() or saved.read_bytes() != stream.getvalue().encode('utf-8'):
                    parser.error(f'CSV устарел: {saved.name}. Запустите scripts/export_answers.py')
                checks['answers'][path.stem] = {'rows': len(rows), 'csv_matches_database': True}
            cur.execute('SELECT issue_code, count(*) FROM mart.quality_issues GROUP BY 1 ORDER BY 1')
            checks['quality_issues'] = dict(cur.fetchall())

    # Та же SQL-логика, что у сборщика; только добавляем явную транзакцию.
    standalone = ('-- Capibara: полная сборка core/mart из уже загруженного raw.\n'
                  '-- PostgreSQL 16+. Обычный SQL без команд клиента psql.\n'
                  '-- Выполнять весь файл как скрипт. При прерывании выполнить ROLLBACK.\n'
                  'BEGIN;\n' + read_build_sql() + '\nCOMMIT;\n')
    if any(line.startswith('\\') for line in standalone.splitlines()):
        parser.error('В едином SQL остались команды клиента psql')
    if args.verify_clean:
        print('Проверка единого SQL на чистой базе...', flush=True)
        checks['standalone_clean_build'] = verify_clean_sql(args.dsn, standalone)
        print('Чистая сборка проверена:', checks['standalone_clean_build'], flush=True)
    payload = {}
    for base, suffixes in [('model', {'.md','.sql','.csv'}), ('scripts', {'.py','.sh','.sql'}), ('tests', {'.sql','.py'}), ('docs', {'.md'}), ('notebooks', {'.ipynb','.html','.png'})]:
        for path in sorted((ROOT / base).rglob('*')):
            if path.is_file() and path.suffix in suffixes and '.ipynb_checkpoints' not in path.parts:
                payload[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for name in ['README.md', 'docker-compose.yml', '.gitignore', 'requirements-notebook.txt']:
        payload[name] = (ROOT / name).read_bytes()
    payload['marketplace_model.sql'] = standalone.encode('utf-8')
    payload['OPEN_FIRST.md'] = '''# Решение Capibara

Начните с [состава сдачи](model/submission/INDEX.md).
Наше решение: [README команды](model/README.md).
Корневой README.md — оригинальный материал организаторов.

`marketplace_model.sql` — единый SQL-файл для сборки после загрузки raw.
Исходные CSV скачиваются штатным скриптом; они не включены в архив.
Вопросы второго блока ещё не опубликованы в текущем docs/tasks.md.
'''.encode('utf-8')
    payload['verification.json'] = (json.dumps(checks, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    # Проверка относительных ссылок именно внутри будущего архива.
    for name, content in payload.items():
        if name.endswith('.md'):
            for target in re.findall(r'\]\(([^)]+)\)', content.decode('utf-8')):
                if '://' in target or target.startswith('#'):
                    continue
                linked = (ROOT / name).parent / target.split('#')[0]
                try:
                    key = linked.resolve().relative_to(ROOT).as_posix()
                except ValueError:
                    parser.error(f'Ссылка выходит из комплекта: {name}: {target}')
                if key not in payload:
                    parser.error(f'Нет файла по ссылке внутри комплекта: {name}: {target}')
    manifest = {name: hashlib.sha256(content).hexdigest() for name, content in sorted(payload.items())}
    payload['manifest.sha256.json'] = (json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    args.output.mkdir(parents=True,exist_ok=True)
    archive = args.output / 'capibara-submission.zip'
    temporary = archive.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, content in sorted(payload.items()):
            bundle.writestr(name, content)
    with zipfile.ZipFile(temporary) as bundle:
        if bundle.testzip() is not None:
            raise RuntimeError('Ошибка целостности ZIP')
        for name, expected in manifest.items():
            if hashlib.sha256(bundle.read(name)).hexdigest() != expected:
                raise RuntimeError(f'Ошибка контрольной суммы: {name}')
    temporary.replace(archive)
    (args.output / 'marketplace_model.sql').write_text(standalone,encoding='utf-8')
    (args.output / 'verification.json').write_bytes(payload['verification.json'])
    print(f'Комплект: {archive}')
    print(f'Файлов: {len(payload)}; размер: {archive.stat().st_size:,} байт')
    print('Пять контрольных ответов, актуальность CSV, ссылки и SHA-256 проверены.')
    print('Вопросы 6–10 и вброс остаются до их публикации организаторами.')


if __name__ == '__main__':
    main()
