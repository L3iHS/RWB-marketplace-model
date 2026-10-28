"""Создаёт дашборд Metabase из metabase/questions/*.sql (стандартная библиотека)."""
import argparse
from getpass import getpass
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
COLLECTION_NAME = 'Capibara · Аналитика продаж v1'
DEFINITIONS = (
    ('01_revenue.sql', 'Товарный оборот · BRL', 'scalar', 0, 0, 8, 4),
    ('02_orders.sql', 'Доставленные заказы', 'scalar', 0, 8, 8, 4),
    ('03_average_check.sql', 'Средний чек с доставкой · BRL', 'scalar', 0, 16, 8, 4),
    ('04_monthly.sql', 'Оборот по месяцам · BRL', 'bar', 4, 0, 12, 7),
    ('04_monthly.sql', 'Заказы по месяцам', 'line', 4, 12, 12, 7),
    ('05_sellers.sql', 'Топ-10 продавцов', 'table', 11, 0, 12, 8),
    ('06_categories.sql', 'Категории и доли оборота', 'table', 11, 12, 12, 8),
    ('07_orders_detail.sql', 'Детализация доставленных заказов', 'table', 19, 0, 24, 9),
    ('08_quality.sql', 'Качество данных · весь набор, без фильтра периода', 'table', 28, 0, 24, 7),
)
PARAMETERS = [
    {'id': 'date_from', 'name': 'Дата с', 'slug': 'date_from', 'type': 'date/single'},
    {'id': 'date_to', 'name': 'Дата по', 'slug': 'date_to', 'type': 'date/single'},
    {'id': 'customer_state', 'name': 'Штат покупателя', 'slug': 'customer_state', 'type': 'string/='},
]


class MetabaseAPI:
    def __init__(self, url):
        self.url = url.rstrip('/')
        self.headers = {}

    def __call__(self, method, path, body=None):
        headers = dict(self.headers)
        data = None
        if body is not None:
            headers['Content-Type'] = 'application/json; charset=utf-8'
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        request = Request(f'{self.url}/api/{path}', data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=120) as response:
                payload = response.read()
        except HTTPError as exc:
            # Не выводим тело ответа: оно может содержать данные входа.
            raise RuntimeError(f'{method} /api/{path}: HTTP {exc.code} {exc.reason}') from exc
        except URLError as exc:
            raise RuntimeError(f'Cannot connect to Metabase: {exc.reason}') from exc
        return json.loads(payload) if payload else None


def create_dashboard(api, database_id, queries):
    if not database_id:
        databases = [db for db in api('GET', 'database')['data']
                     if db.get('engine') == 'postgres'
                     and db.get('details', {}).get('dbname') == 'marketplace']
        if len(databases) != 1:
            raise RuntimeError('Specify --database-id from the Marketplace database settings URL.')
        database_id = databases[0]['id']
    if any(c['name'] == COLLECTION_NAME and not c.get('archived')
           for c in api('GET', 'collection')):
        raise RuntimeError('Dashboard collection already exists. Edit it in Metabase; '
                           'this script will not overwrite it or create duplicates.')
    collection = api('POST', 'collection', {
        'name': COLLECTION_NAME,
        'description': 'Продажи доставленных заказов по дате оформления. Денежные значения в BRL.',
    })
    dashboard = api('POST', 'dashboard', {
        'name': 'Capibara · Анализ продаж', 'collection_id': collection['id'],
        'description': 'Доставленные заказы по дате оформления. Оборот без доставки; средний чек с доставкой. '
                       'Качество данных относится ко всему набору. NULL среднего чека означает отсутствие известных сумм.',
        'parameters': PARAMETERS,
    })
    dashboard_path = f"dashboard/{dashboard['id']}"
    print(f'Created dashboard: {api.url}/{dashboard_path}')
    dashcards = []
    for index, (filename, name, display, row, col, size_x, size_y) in enumerate(DEFINITIONS, 1):
        filtered = filename != '08_quality.sql'
        tags = {}
        if filtered:
            for parameter in PARAMETERS:
                key = parameter['id']
                tags[key] = {
                    'id': str(uuid4()), 'name': key, 'display-name': parameter['name'],
                    'type': 'text' if key == 'customer_state' else 'date', 'required': False,
                }
        settings = {}
        if display in ('bar', 'line'):
            settings = {
                'graph.dimensions': ['month'],
                'graph.metrics': ['revenue_brl' if display == 'bar' else 'delivered_orders'],
            }
        card = api('POST', 'card', {
            'name': name, 'collection_id': collection['id'], 'display': display,
            'visualization_settings': settings,
            'dataset_query': {
                'database': database_id, 'type': 'native',
                'native': {'query': queries[filename], 'template-tags': tags},
            },
        })
        mappings = [
            {'parameter_id': p['id'], 'card_id': card['id'],
             'target': ['variable', ['template-tag', p['id']]]}
            for p in PARAMETERS
        ] if filtered else []
        dashcards.append({
            'id': -index, 'card_id': card['id'], 'row': row, 'col': col,
            'size_x': size_x, 'size_y': size_y, 'parameter_mappings': mappings,
            'visualization_settings': {},
        })
        # Сохраняем каждую карточку, чтобы результат был виден при частичной ошибке.
        updated = api('PUT', dashboard_path, {'dashcards': dashcards})
        dashcards = updated['dashcards']
    print(f'Ready: {api.url}/{dashboard_path}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://localhost:3000', help='Metabase URL')
    parser.add_argument('--database-id', type=int, default=0, help='Marketplace database ID (default: auto-detect)')
    parser.add_argument('--validate-only', action='store_true', help='Read SQL files without connecting to Metabase')
    args = parser.parse_args(argv)
    if args.database_id < 0:
        parser.error('--database-id must be positive (or 0 for auto-detection)')
    try:
        queries = {d[0]: (ROOT / 'metabase' / 'questions' / d[0]).read_text(encoding='utf-8-sig')
                   for d in DEFINITIONS}
        if args.validate_only:
            print(f'Validated {len(DEFINITIONS)} card definitions and SQL file paths.')
            return 0
        api = MetabaseAPI(args.url)
        if api('GET', 'health').get('status') != 'ok':
            raise RuntimeError('Metabase is not ready.')
        username = input('Metabase email: ').strip()
        password = getpass('Metabase password: ')
        session = api('POST', 'session', {'username': username, 'password': password})
        del password
        api.headers['X-Metabase-Session'] = session['id']
        try:
            create_dashboard(api, args.database_id, queries)
        finally:
            try:
                api('DELETE', 'session')
            except (RuntimeError, OSError, ValueError):
                print('Warning: could not close Metabase session.', file=sys.stderr)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print('\nCancelled.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
