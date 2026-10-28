"""Read-only API: один согласованный снимок модели на ответ и выгрузку."""
from contextlib import contextmanager
import csv
from datetime import date, datetime
from decimal import Decimal
import io
import logging
import os
from pathlib import Path
import re
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
import psycopg2

app = FastAPI(title='Marketplace Analytics', version='1.0.0')
logger = logging.getLogger(__name__)

DEFINITIONS = [
    dict(id='revenue_brl', label='Товарный оборот', formula='SUM(goods_amount)', grain='Заказ',
         status_scope='Только доставленные', date_field='Дата оформления заказа',
         notes='Стоимость товаров без доставки, BRL. Это оборот продавцов, а не доход площадки.'),
    dict(id='delivered_orders', label='Доставленные заказы', formula='COUNT(*) WHERE is_delivered', grain='Заказ',
         status_scope='Только доставленные', date_field='Дата оформления заказа',
         notes='Один заказ считается один раз, независимо от числа товаров, платежей и отзывов.'),
    dict(id='average_check_brl', label='Средний чек с доставкой', formula='AVG(order_amount)', grain='Заказ',
         status_scope='Только доставленные', date_field='Дата оформления заказа',
         notes='Товары и доставка. Неизвестные суммы пропускаются; средние по группам нельзя складывать.'),
    dict(id='repeat_pct', label='Повторные покупатели', formula='Покупатели с 2+ заказами / все покупатели × 100',
         grain='Человек: customer_unique_id', status_scope='Все статусы в выбранном срезе',
         date_field='Дата оформления заказа', notes='Возврат означает повторное оформление. При фильтрации период/штат применяются к обоим заказам. Уникальных покупателей по срезам нельзя складывать.'),
    dict(id='late_pct', label='Доля опозданий', formula='Доставленные позже обещанной даты / доставленные с обеими датами × 100',
         grain='Заказ', status_scope='Только доставленные', date_field='Дата оформления заказа',
         notes='Даты сравниваются по календарным дням. Отсутствующие даты показаны отдельно и не считаются доставкой вовремя. Доли нельзя складывать.'),
    dict(id='quality', label='Качество данных', formula='COUNT(*) по severity/issue_code/entity_type', grain='Проблема сущности',
         status_scope='Весь набор', date_field='Без фильтра периода',
         notes='Одна сущность может иметь несколько проблем; количество проблем не равно количеству заказов.'),
]

SCOPED = '''WITH selected_orders AS (
    SELECT * FROM mart.order_totals
    WHERE (%(date_from)s::date IS NULL OR purchased_at >= %(date_from)s::date)
      AND (%(date_to)s::date IS NULL OR purchased_at < %(date_to)s::date + interval '1 day')
      AND (%(state)s::text IS NULL OR customer_state = %(state)s::text)
) '''

REPORTS = {
    'monthly': SCOPED + ''' , months AS (
        SELECT DISTINCT month FROM core.calendar
        WHERE month >= date_trunc('month', coalesce(%(date_from)s::date, (SELECT min(purchased_at)::date FROM core.orders)))
          AND month <= date_trunc('month', coalesce(%(date_to)s::date, (SELECT max(purchased_at)::date FROM core.orders)))
    ), totals AS (
        SELECT purchase_month AS month, sum(goods_amount) AS revenue_brl, count(*) AS delivered_orders
        FROM selected_orders WHERE is_delivered GROUP BY 1
    ) SELECT m.month, coalesce(t.revenue_brl,0) AS revenue_brl,
             coalesce(t.delivered_orders,0) AS delivered_orders
      FROM months m LEFT JOIN totals t USING(month) ORDER BY m.month''',
    'sellers': SCOPED + '''SELECT d.seller_id, s.city, s.state, count(DISTINCT d.order_id) AS orders,
                                 count(*) AS units, sum(d.price) AS revenue_brl
        FROM mart.delivered_items d JOIN selected_orders o USING(order_id)
        JOIN core.sellers s USING(seller_id)
        GROUP BY d.seller_id,s.city,s.state ORDER BY revenue_brl DESC,d.seller_id''',
    'categories': SCOPED + '''SELECT d.category_key,c.name,sum(d.price) AS revenue_brl,
             round(100 * sum(d.price) / nullif(sum(sum(d.price)) OVER(),0),2) AS revenue_pct
        FROM mart.delivered_items d JOIN selected_orders o USING(order_id)
        JOIN core.categories c USING(category_key)
        GROUP BY d.category_key,c.name ORDER BY revenue_brl DESC,d.category_key''',
    'statuses': SCOPED + '''SELECT status_code,count(*) AS orders,
             round(100.0 * count(*) / nullif(sum(count(*)) OVER(),0),2) AS orders_pct,
             count(*) FILTER(WHERE units=0) AS orders_without_items
        FROM selected_orders GROUP BY status_code ORDER BY orders DESC,status_code''',
    'delivery': SCOPED + '''SELECT customer_state AS state,count(*) AS orders,
             count(is_late) AS known_delivery_dates,round(avg(delivery_days),2) AS average_days,
             count(*) FILTER(WHERE is_late) AS late_orders,
             round(100.0 * count(*) FILTER(WHERE is_late) / nullif(count(is_late),0),2) AS late_pct,
             count(*) FILTER(WHERE is_late IS NULL) AS missing_dates
        FROM selected_orders WHERE is_delivered GROUP BY customer_state ORDER BY orders DESC,customer_state''',
    'quality': '''SELECT severity,issue_code,entity_type,count(*) AS issues,
                    count(DISTINCT entity_id) AS affected_entities
        FROM mart.quality_issues GROUP BY severity,issue_code,entity_type
        ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,issues DESC,issue_code''',
    'orders': SCOPED + '''SELECT order_id,purchased_at,status_code,customer_state AS state,
             goods_amount,freight_amount,order_amount,units,lines,delivery_days,is_late,latest_review_score
        FROM selected_orders ORDER BY purchased_at DESC,order_id''',
}

QUESTIONS = {
    '6': ('История цен товара', '06_price_history.sql'),
    '7': ('Доставка по штатам: от 500 заказов', '07_delivery_by_state.sql'),
    '8': ('Распределение заказов по статусам', '08_status_funnel.sql'),
    '9a': ('Платежи и рассрочка по штатам за 2018 год', '09a_payments_by_state.sql'),
    '9b': ('Платежи и рассрочка по способам оплаты', '09b_payments_by_type.sql'),
    '10': ('Оценки покупателей и сроки доставки', '10_review_vs_delivery.sql'),
}
ANSWERS_DIR = Path(__file__).resolve().parent.parent / 'answers'


def connect_database(dbname=None):
    return psycopg2.connect(host=os.getenv('PGHOST', 'localhost'), port=os.getenv('PGPORT', '5433'),
                            dbname=dbname or os.getenv('PGDATABASE', 'marketplace'), user=os.getenv('PGUSER', 'hack'),
                            password=os.getenv('PGPASSWORD', 'hack'), connect_timeout=5)


@contextmanager
def snapshot(dbname=None):
    conn = connect_database() if dbname is None else connect_database(dbname)
    try:
        with conn, conn.cursor() as cur:
            cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            cur.execute("SET LOCAL statement_timeout='30s'")
            cur.execute("SET LOCAL lock_timeout='5s'")
            cur.execute("SET LOCAL TIME ZONE 'UTC'")
            cur.execute("SET LOCAL datestyle='ISO,YMD'")
            cur.execute('SET LOCAL max_parallel_workers_per_gather=0')
            yield cur
    finally:
        conn.close()


def records(cur, statement, params=None):
    cur.execute(statement, params)
    columns = [c.name for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def serializable(value):
    if isinstance(value, Decimal):
        return format(value, 'f')
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(v) for v in value]
    return value


def parse_filters(date_from: str | None = None, date_to: str | None = None, state: str | None = None):
    try:
        if any(value and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) for value in (date_from, date_to)):
            raise ValueError('Неверный формат даты')
        start = date.fromisoformat(date_from) if date_from else None
        end = date.fromisoformat(date_to) if date_to else None
    except ValueError as exc:
        raise HTTPException(422, 'Дата должна иметь формат ГГГГ-ММ-ДД') from exc
    if start and end and start > end:
        raise HTTPException(422, 'Начало периода должно быть не позже окончания')
    return dict(date_from=start, date_to=end, state=state.strip().upper() if state and state.strip() else None)


def context_and_options(cur, params):
    bounds = records(cur, 'SELECT min(purchased_at)::date AS date_min,max(purchased_at)::date AS date_max FROM core.orders')[0]
    cur.execute('SELECT DISTINCT customer_state FROM mart.order_totals WHERE customer_state IS NOT NULL ORDER BY 1')
    states = [r[0] for r in cur.fetchall()]
    if params['state'] is not None and params['state'] not in states:
        raise HTTPException(422, 'Неизвестный штат покупателя')
    context = dict(dataset_version='original', kind='original', currency='BRL', published_at=None,
                   data_from=bounds['date_min'], data_to=bounds['date_max'])
    cur.execute("SELECT to_regclass('ops.current_dataset')")
    if cur.fetchone()[0]:
        publication = records(cur, '''SELECT v.version_id,v.kind,v.published_at
            FROM ops.current_dataset c JOIN ops.dataset_versions v USING(version_id)''')
        if publication:
            context.update(dataset_version=publication[0]['version_id'], kind=publication[0]['kind'],
                           published_at=publication[0]['published_at'])
    return context, dict(states=states, **bounds)


def dashboard_data(cur, params):
    context, options = context_and_options(cur, params)
    summary = records(cur, SCOPED + ''', buyers AS (
        SELECT customer_unique_id,count(*) AS orders FROM selected_orders GROUP BY customer_unique_id
    ) SELECT coalesce(sum(goods_amount) FILTER(WHERE is_delivered),0) AS revenue_brl,
             count(*) FILTER(WHERE is_delivered) AS delivered_orders,
             round(avg(order_amount) FILTER(WHERE is_delivered),2) AS average_check_brl,
             (SELECT count(*) FROM buyers) AS buyers,
             (SELECT count(*) FROM buyers WHERE orders>1) AS repeat_buyers,
             (SELECT round(100.0 * count(*) FILTER(WHERE orders>1) / nullif(count(*),0),2) FROM buyers) AS repeat_pct
        FROM selected_orders''', params)[0]
    payload = dict(context=context, filters=params, options=options, summary=summary, definitions=DEFINITIONS)
    for name, statement in REPORTS.items():
        limit = ' LIMIT 50' if name == 'orders' else ''
        payload[name] = records(cur, statement + limit, params)
    cur.execute(SCOPED + 'SELECT count(*) FROM selected_orders', params)
    payload['orders_total'] = cur.fetchone()[0]
    return serializable(payload)


def question_sql(question_id):
    if question_id not in QUESTIONS:
        raise HTTPException(404, 'Неизвестный номер вопроса')
    title, filename = QUESTIONS[question_id]
    return title, filename, (ANSWERS_DIR / filename).read_text(encoding='utf-8')


def csv_text(cur):
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\n')
    writer.writerow([c.name for c in cur.description])
    writer.writerows(cur)
    return output.getvalue()


def csv_response(content, report, version):
    safe_version = re.sub(r'[^a-zA-Z0-9_-]', '-', version)[:64]
    return Response(content, media_type='text/csv', headers={
        'Content-Disposition': f'attachment; filename="marketplace-{report}-{safe_version}.csv"',
        'X-Dataset-Version': version,
    })


def ensure_version(context, expected_version):
    if context['dataset_version'] != expected_version:
        raise HTTPException(409, 'Набор данных обновился. Обновите дашборд перед выгрузкой.')


@app.exception_handler(RequestValidationError)
async def validation_error(_request, _error):
    return JSONResponse(status_code=422, content={'detail': 'Проверьте параметры запроса'})


@app.exception_handler(psycopg2.Error)
async def database_error(_request, _error):
    logger.error('Не удалось прочитать аналитическую модель', exc_info=_error)
    return JSONResponse(status_code=503, content={'detail': 'Модель данных временно недоступна. Проверьте запуск PostgreSQL и сборку модели.'})


@app.get('/api/health')
def health():
    with snapshot() as cur:
        cur.execute('''SELECT bool_and(to_regclass(relation) IS NOT NULL)
            FROM unnest(ARRAY['core.orders', 'core.calendar', 'core.categories', 'core.sellers',
                             'mart.order_totals', 'mart.delivered_items', 'mart.quality_issues']) AS relation''')
        if not cur.fetchone()[0]:
            raise HTTPException(503, 'Модель ещё не собрана')
        cur.execute('SELECT 1 FROM mart.order_totals LIMIT 1')
    return {'status': 'ok'}


def selected_snapshot(dataset):
    return snapshot('marketplace_demo_dashboard') if dataset == 'demo' else snapshot()


@app.get('/api/dashboard')
def dashboard(params=Depends(parse_filters), dataset: Literal['original', 'demo'] = 'original'):
    with selected_snapshot(dataset) as cur:
        return dashboard_data(cur, params)


@app.get('/api/export')
def export(report: Literal['orders', 'monthly', 'sellers', 'categories', 'delivery', 'statuses', 'quality'],
           expected_version: str = Query(min_length=1, max_length=128), params=Depends(parse_filters),
           dataset: Literal['original', 'demo'] = 'original'):
    with selected_snapshot(dataset) as cur:
        context, _ = context_and_options(cur, params)
        ensure_version(context, expected_version)
        cur.execute(REPORTS[report], params)
        content = csv_text(cur)
    return csv_response(content, report, context['dataset_version'])


@app.get('/api/questions')
def questions(dataset: Literal['original', 'demo'] = 'original'):
    with selected_snapshot(dataset) as cur:
        context, _ = context_and_options(cur, parse_filters())
        results = []
        for question_id in QUESTIONS:
            title, filename, statement = question_sql(question_id)
            cur.execute(statement)
            columns = [c.name for c in cur.description]
            rows = cur.fetchall()
            results.append(dict(id=question_id, title=title, columns=columns, rows=rows,
                                row_count=len(rows), sql_file=f'answers/{filename}', sql=statement))
        return serializable(dict(context=context, questions=results))


@app.get('/api/questions/{question_id}/export')
def question_export(question_id: str, expected_version: str = Query(min_length=1, max_length=128),
                    dataset: Literal['original', 'demo'] = 'original'):
    _, _, statement = question_sql(question_id)
    with selected_snapshot(dataset) as cur:
        context, _ = context_and_options(cur, parse_filters())
        ensure_version(context, expected_version)
        cur.execute(statement)
        content = csv_text(cur)
    return csv_response(content, f'question-{question_id}', context['dataset_version'])


@app.get('/api/history')
def history(product_id: str | None = Query(default=None, max_length=128),
            order_id: str | None = Query(default=None, max_length=128),
            dataset: Literal['original', 'demo'] = 'original'):
    from backend.history import history_data

    with selected_snapshot(dataset) as cur:
        context, _ = context_and_options(cur, parse_filters())
        data = history_data(cur, product_id=product_id or None, order_id=order_id or None)
        return serializable(dict(context=context, **data))


from backend.demo import router as demo_router  # noqa: E402

app.include_router(demo_router)
