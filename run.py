"""Единая точка входа проекта: подготовка, сборка, проверки, ответы, тесты.

Обычно запускается в Docker, тогда на машине нужен только Docker:

    docker compose run --rm app setup      данные + загрузка raw
    docker compose run --rm app build      сборка core и mart с проверками
    docker compose run --rm app check      сверка с контрольными цифрами
    docker compose run --rm app test       тесты
    docker compose run --rm app answers    ответы на экран и комплект в artifacts/runtime/answers/
    docker compose run --rm app preview    первые строки таблиц
    docker compose run --rm app explore    разведка raw
    docker compose run --rm app sql FILE   выполнить любые SQL-файлы

Можно запускать и без Docker (python run.py build), если на машине есть
Python с пакетами из requirements.txt и psql, а база доступна по PGHOST/PGPORT.

Параметры подключения — стандартные переменные PostgreSQL:
PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD. В контейнере их задаёт
docker-compose.yml, без Docker действуют значения по умолчанию из scripts/db.py.
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / 'data'
DATA_REVISION = 'd9e49802f3e92d09ee94ab9ccc5e457f207a8959'
DATA_URL = f'https://raw.githubusercontent.com/olist/work-at-olist-data/{DATA_REVISION}/datasets/'
DATA_FILES = [
    'olist_orders_dataset.csv',
    'olist_order_items_dataset.csv',
    'olist_order_payments_dataset.csv',
    'olist_order_reviews_dataset.csv',
    'olist_products_dataset.csv',
    'olist_sellers_dataset.csv',
    'olist_customers_dataset.csv',
    'product_category_name_translation.csv',
]
# SHA-256 исходной выгрузки: непустой, но оборванный или другой CSV не считается готовым.
DATA_SHA256 = {
    'olist_orders_dataset.csv': '8df58ef3d2d7e9944010f7beecd9b75367f5588ec6e3c91cec19ae3345ef9ecf',
    'olist_order_items_dataset.csv': '4f6abdbbc94036d0df4a76fa0520c072e31a40119d70f7f370fba1e2285d2bcb',
    'olist_order_payments_dataset.csv': '61674868ed7b872aac3dcd95bf774448a88f6426b183f21be55f75af021ffdec',
    'olist_order_reviews_dataset.csv': '012b61c7593e34f51fa614efdf802b9c7056ce6aae5307ddb93236e7cfc797d7',
    'olist_products_dataset.csv': '3e6569628a17fbc75fd206ee357b59e20364b9afa90f5b6cd5b4d624c58aa9cc',
    'olist_sellers_dataset.csv': '31eb9bd50d684526a78f2389413ce61841e97692de7b828fe7d956b534586312',
    'olist_customers_dataset.csv': 'c26c17f59f3027a6a0dbeb8f1fa373c38f3323ecc84f225a8f4820e5bb288df8',
    'product_category_name_translation.csv': 'a81f0d1f27b27e7293f761bc79e3ce8f348ee39c4b3ed3e49bde38f478586278',
}

# Настройки, которые действуют на всю транзакцию сборки.
SESSION_SETTINGS = [
    # Не ждать бесконечно, если таблицы заняты другим запросом,
    # и не дать зависшему запросу держать базу.
    "SET LOCAL lock_timeout = '5s';",
    "SET LOCAL statement_timeout = '120s';",
    # Даты в raw — в формате ГГГГ-ММ-ДД; фиксируем, чтобы разбор не зависел от настроек сервера.
    "SET LOCAL datestyle = 'ISO, YMD';",
    # Параллельные запросы берут разделяемую память, а Docker по умолчанию даёт
    # контейнеру лишь 64 МБ /dev/shm. На нашем объёме параллельность не нужна.
    'SET LOCAL max_parallel_workers_per_gather = 0;',
]


def conn_params():
    """Параметры подключения из переменных окружения (как у psql и libpq)."""
    return {
        'host': os.getenv('PGHOST', 'localhost'),
        'port': os.getenv('PGPORT', '5433'),
        'db': os.getenv('PGDATABASE', 'marketplace'),
        'user': os.getenv('PGUSER', 'hack'),
        'password': os.getenv('PGPASSWORD', 'hack'),
    }


def python_script(name, *args):
    """Запускает Python-скрипт из scripts/ тем же интерпретатором, что и run.py."""
    return subprocess.run([sys.executable, str(ROOT / 'scripts' / name), *args], cwd=ROOT).returncode


def sql(files):
    """Выполняет SQL-файлы одной транзакцией через psql.

    При ошибке в любом месте изменения откатываются целиком,
    и в базе остаётся прежняя версия модели.
    """
    if shutil.which('psql') is None:
        sys.exit('Не найден psql. Запускайте через Docker: docker compose run --rm app <команда>')

    p = conn_params()
    script = ['BEGIN;', *SESSION_SETTINGS]
    for f in files:
        path = ROOT / f
        if not path.exists():
            sys.exit(f'Нет файла: {f}')
        script.append(f"\\echo '==> {f}'")
        script.append(path.read_text(encoding='utf-8'))
    script.append('COMMIT;')

    print(f"База: {p['db']}. Файлы: {' '.join(str(f) for f in files)}", flush=True)
    result = subprocess.run(
        ['psql', '-h', p['host'], '-p', p['port'], '-U', p['user'], '-d', p['db'],
         '-v', 'ON_ERROR_STOP=1', '-q', '-X'],
        input='\n'.join(script), text=True, encoding='utf-8',
        env={**os.environ, 'PGPASSWORD': p['password']},
    )
    if result.returncode == 0:
        print('Готово.')
    return result.returncode


def build():
    """Сборка core и mart из raw с нуля, с проверками внутри."""
    return sql([p.relative_to(ROOT).as_posix() for p in sorted((ROOT / 'model').glob('*.sql'))])


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def download_data():
    """Принимает только проверенные оригиналы; сбой не публикует временный файл."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in DATA_FILES:
        target = DATA_DIR / name
        expected = DATA_SHA256[name]
        if target.is_file() and file_sha256(target) == expected:
            continue
        print(f'  качаю {name}', flush=True)
        descriptor, filename = tempfile.mkstemp(prefix=f'.{name}.', suffix='.part', dir=DATA_DIR)
        tmp = Path(filename)
        try:
            with os.fdopen(descriptor, 'wb') as destination:
                with urllib.request.urlopen(DATA_URL + name, timeout=60) as response:
                    shutil.copyfileobj(response, destination)
                destination.flush()
                os.fsync(destination.fileno())
            actual = file_sha256(tmp)
            if actual != expected:
                raise ValueError(f'{name}: SHA-256 не совпал; файл не принят ({actual})')
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
    print(f'  проверены SHA-256: {len(DATA_FILES)} файлов в data/')


def wait_for_db(timeout=60):
    """Ждёт, пока база начнёт принимать подключения."""
    import psycopg2
    p = conn_params()
    deadline = time.time() + timeout
    while True:
        try:
            psycopg2.connect(host=p['host'], port=p['port'], dbname=p['db'],
                             user=p['user'], password=p['password']).close()
            return
        except psycopg2.OperationalError:
            if time.time() > deadline:
                sys.exit('База не ответила. Проверьте: docker compose logs postgres')
            time.sleep(2)


def raw_orders_count():
    """Сколько заказов уже лежит в raw; 0, если raw ещё не создан."""
    import psycopg2
    p = conn_params()
    with psycopg2.connect(host=p['host'], port=p['port'], dbname=p['db'],
                          user=p['user'], password=p['password']) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('raw.orders') IS NOT NULL")
        if not cur.fetchone()[0]:
            return 0
        cur.execute('SELECT count(*) FROM raw.orders')
        return cur.fetchone()[0]


def setup(reload_raw):
    """Скачивает данные и загружает raw, если он ещё пуст."""
    print('==> Данные')
    download_data()
    print('==> База')
    wait_for_db()
    rows = raw_orders_count()
    if rows and not reload_raw:
        print(f'  raw уже содержит {rows} заказов, перезагрузка не нужна (--reload, чтобы перезалить)')
        return 0
    print('==> Загрузка raw')
    p = conn_params()
    return python_script('load_raw.py', '--host', p['host'], '--port', p['port'], '--db', p['db'],
                         '--user', p['user'], '--password', p['password'])


def main():
    # Кириллица в выводе: на Windows консоль по умолчанию не в UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(
        prog='run.py', description='Модель маркетплейса Capibara: сборка, проверки, ответы.')
    commands = parser.add_subparsers(dest='command', metavar='команда')
    setup_cmd = commands.add_parser('setup', help='скачать данные и загрузить raw')
    setup_cmd.add_argument('--reload', action='store_true', help='перезалить raw, даже если он уже загружен')
    commands.add_parser('build', help='собрать core и mart с нуля (26 проверок внутри)')
    commands.add_parser('check', help='сверить ответы с контрольными цифрами задания')
    commands.add_parser('test', help='запустить тесты')
    answers_cmd = commands.add_parser('answers', help='показать ответы 1–10 и опубликовать полный комплект')
    answers_cmd.add_argument('--output-dir', help='каталог результатов (по умолчанию artifacts/runtime/answers/)')
    commands.add_parser('preview', help='первые строки таблиц; параметры как у scripts/preview.py: -n 10 -t orders')
    commands.add_parser('explore', help='разведка raw')
    commands.add_parser('profile', help='профиль raw в artifacts/profile.json')
    sql_cmd = commands.add_parser('sql', help='выполнить SQL-файлы одной транзакцией')
    sql_cmd.add_argument('files', nargs='+', help='пути от корня репозитория, например answers/02_top_sellers.sql')
    # Неизвестные параметры передаём в preview.py (-n, -t, -s, --colwidth),
    # для остальных команд они — ошибка.
    args, extra = parser.parse_known_args()
    if extra and args.command != 'preview':
        parser.error('неизвестные параметры: ' + ' '.join(extra))

    if args.command == 'setup':
        code = setup(args.reload)
    elif args.command == 'build':
        code = build()
    elif args.command == 'check':
        code = sql(['answers/99_controls.sql'])
    elif args.command == 'test':
        code = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=ROOT).returncode
    elif args.command == 'answers':
        options = ['--output-dir', args.output_dir] if args.output_dir else []
        code = python_script('answers.py', *options)
    elif args.command == 'preview':
        code = python_script('preview.py', *extra)
    elif args.command == 'explore':
        code = sql(['explore/01_profiling.sql'])
    elif args.command == 'profile':
        code = python_script('profile.py')
    elif args.command == 'sql':
        code = sql(args.files)
    else:
        parser.print_help()
        code = 0
    sys.exit(code)


if __name__ == '__main__':
    main()
