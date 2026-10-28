"""Приём полного снимка без изменения исходного raw и без пересоздания core."""
import json
from pathlib import Path
import uuid

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json

from batches import FILES, archive_batch, fingerprint, sha256
from db import connect
from provenance import hash_records, model_schema_fingerprint

ROOT = Path(__file__).resolve().parent.parent
PUBLISH_LOCK = 72620261028
CORE_DELETE_ORDER = (
    'order_reviews', 'order_payments', 'order_items', 'order_addresses', 'orders',
    'product_category_history', 'products',
    'customer_order_profiles', 'customers', 'sellers', 'categories', 'order_statuses', 'calendar',
)


def initialize(cur):
    cur.execute((ROOT / 'scripts/sql/ingestion.sql').read_text(encoding='utf-8'))


def input_signature(directory):
    path = Path(directory) / 'manifest.json'
    return sha256(path) if path.is_file() else 'missing-manifest'


def current_version(cur):
    cur.execute("SELECT to_regclass('ops.current_dataset')")
    if cur.fetchone()[0] is None:
        return None
    cur.execute('''SELECT to_jsonb(v) FROM ops.current_dataset c
                   JOIN ops.dataset_versions v USING (version_id)''')
    row = cur.fetchone()
    return row[0] if row else None


def load_stage(cur, directory):
    for name, (table, columns) in FILES.items():
        cur.execute(sql.SQL('CREATE TEMP TABLE {} (LIKE raw.{} INCLUDING DEFAULTS) ON COMMIT DROP')
                    .format(sql.Identifier('stage_' + table), sql.Identifier(table)))
        statement = sql.SQL('COPY {} ({}) FROM STDIN WITH (FORMAT csv, HEADER true)').format(
            sql.Identifier('stage_' + table), sql.SQL(',').join(map(sql.Identifier, columns)))
        with (directory / name).open(encoding='utf-8-sig', newline='') as f:
            cur.copy_expert(statement, f)
        cur.execute(sql.SQL('UPDATE {} SET _source_file = %s').format(sql.Identifier('stage_' + table)), (name,))


def preserve_history(cur):
    for table, condition in (
        ('orders', 'n.order_id = old.order_id'),
        ('order_items', 'n.order_id = old.order_id AND n.order_item_id::integer = old.order_item_id'),
        ('order_payments', 'n.order_id = old.order_id AND n.payment_sequential::integer = old.payment_sequential'),
        ('order_reviews', 'n.order_id = old.order_id AND n.review_id = old.review_id'),
        ('products', 'n.product_id = old.product_id'),
    ):
        cur.execute(sql.SQL('SELECT count(*) FROM core.{} old WHERE NOT EXISTS '
                            '(SELECT 1 FROM {} n WHERE ' + condition + ')')
                    .format(sql.Identifier(table), sql.Identifier('stage_' + table)))
        if cur.fetchone()[0]:
            raise ValueError(f'{table}: снимок теряет ранее опубликованные ключи; нужен полный набор истории')
    cur.execute('''SELECT count(*) FROM stage_order_items n JOIN core.order_items old
                   ON n.order_id=old.order_id AND n.order_item_id::integer=old.order_item_id
                   WHERE n.product_id IS DISTINCT FROM old.product_id''')
    if cur.fetchone()[0]:
        raise ValueError('order_items: существующая позиция не может сменить product_id')
    cur.execute('''SELECT count(*) FROM stage_customers n
                   JOIN core.customer_order_profiles old USING(customer_id)
                   WHERE n.customer_unique_id IS DISTINCT FROM old.customer_unique_id''')
    if cur.fetchone()[0]:
        raise ValueError('customers: существующий customer_id не может сменить покупателя')


def check_model(cur, statement):
    cur.execute(statement.replace('raw.', 'pg_temp.stage_'))


def replace_model(cur, load_sql, checks_sql):
    # История и адреса сохраняются в снимке той же транзакции, без отдельного COMMIT.
    for temporary, statement in (
        ('prior_categories', 'SELECT category_key,name_pt,name_en FROM core.categories'),
        ('prior_product_categories', 'SELECT * FROM core.product_category_history'),
        ('prior_item_categories', 'SELECT order_id,order_item_id,product_id,category_version_no FROM core.order_items'),
        ('prior_order_addresses', 'SELECT * FROM core.order_addresses'),
    ):
        cur.execute(sql.SQL('CREATE TEMP TABLE {} ON COMMIT DROP AS ' + statement)
                    .format(sql.Identifier(temporary)))
    for table in CORE_DELETE_ORDER:
        cur.execute(sql.SQL('DELETE FROM core.{}').format(sql.Identifier(table)))
    # Выполняем тот же SQL, что в build; меняется только адрес входных таблиц.
    cur.execute(load_sql.replace('raw.', 'pg_temp.stage_'))
    check_model(cur, checks_sql)


def model_summary(cur):
    cur.execute('''SELECT count(*), count(*) FILTER (WHERE is_delivered),
                          coalesce(sum(goods_amount),0),
                          coalesce(sum(goods_amount) FILTER (WHERE is_delivered),0), max(purchased_at)
                   FROM mart.order_totals''')
    row = cur.fetchone()
    cur.execute('SELECT severity, issue_code, count(*) FROM mart.quality_issues GROUP BY 1,2 ORDER BY 1,2')
    return dict(orders=row[0], delivered_orders=row[1], goods_amount=str(row[2]),
                delivered_goods_amount=str(row[3]), latest_purchase=str(row[4]),
                quality=[dict(severity=s, issue_code=c, rows=n) for s, c, n in cur.fetchall()])


def finish_attempt(cur, attempt_id, status, version_id=None, error=None):
    cur.execute('''UPDATE ops.ingestion_attempts SET status=%s, version_id=%s, error=%s,
                   finished_at=clock_timestamp() WHERE attempt_id=%s''',
                (status, version_id, error, attempt_id))


def ingest(directory, archive_root, dbname=None):
    directory = Path(directory).resolve()
    attempt_id = uuid.uuid4().hex
    conn = connect(dbname)
    locked, received = False, False
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT pg_try_advisory_lock(%s)', (PUBLISH_LOCK,))
            locked = cur.fetchone()[0]
            if not locked:
                return dict(status='busy', error='Другой загрузчик уже публикует данные')
            cur.execute("SET lock_timeout='5s'")
            cur.execute("SET statement_timeout='120s'")
            cur.execute("SET datestyle='ISO, YMD'")
            cur.execute("SET max_parallel_workers_per_gather=0")
            initialize(cur)
            # Владение общей блокировкой означает, что незавершённые попытки
            # предыдущего процесса больше не могут публиковать данные.
            cur.execute("""UPDATE ops.ingestion_attempts SET status='failed',
                           error='Процесс прерван до завершения публикации', finished_at=clock_timestamp()
                           WHERE finished_at IS NULL""")
            signature = input_signature(directory)
            cur.execute('''INSERT INTO ops.ingestion_attempts
                           (attempt_id,input_path,input_signature,status) VALUES (%s,%s,%s,'received')''',
                        (attempt_id, str(directory), signature))
        conn.commit()
        received = True
        with conn.cursor() as cur:
            cur.execute("UPDATE ops.ingestion_attempts SET status='validating' WHERE attempt_id=%s", (attempt_id,))
        conn.commit()
        archive, manifest = archive_batch(directory, archive_root, attempt_id)
        load_sql = (ROOT / 'model/02_load.sql').read_text(encoding='utf-8')
        checks_sql = (ROOT / 'model/90_checks.sql').read_text(encoding='utf-8')
        transform_hash = hash_records([('02_load.sql', load_sql), ('90_checks.sql', checks_sql)])
        dataset_hash = fingerprint(manifest)
        with conn.cursor() as cur:
            cur.execute('UPDATE ops.ingestion_attempts SET archive_path=%s WHERE attempt_id=%s', (str(archive), attempt_id))
        conn.commit()
        with conn.cursor() as cur:
            current = current_version(cur)
            schema_hash = model_schema_fingerprint(conn)
            if current and (current['schema_sha256'] != schema_hash or current['transform_sha256'] != transform_hash):
                raise ValueError('Модель или SQL изменены после публикации; требуется явная пересборка/миграция')
            cur.execute('''SELECT version_id FROM ops.dataset_versions WHERE dataset_sha256=%s
                           AND transform_sha256=%s AND schema_sha256=%s''',
                        (dataset_hash, transform_hash, schema_hash))
            known = cur.fetchone()
            if known:
                status = 'skipped' if current and known[0] == current['version_id'] else 'stale_batch'
                finish_attempt(cur, attempt_id, status, known[0])
                conn.commit()
                return dict(status=status, attempt_id=attempt_id, version_id=known[0])
            if current and (manifest['source_id'] != current['source_id'] or manifest['sequence'] <= current['sequence']):
                finish_attempt(cur, attempt_id, 'stale_batch', error='Другой источник или непоследовательный снимок')
                conn.commit()
                return dict(status='stale_batch', attempt_id=attempt_id)
            cur.execute("UPDATE ops.ingestion_attempts SET status='publishing' WHERE attempt_id=%s", (attempt_id,))
        conn.commit()
        with conn.cursor() as cur:
            load_stage(cur, archive)
            preserve_history(cur)
            cur.execute('SELECT count(*) FROM stage_orders n WHERE NOT EXISTS '
                        '(SELECT 1 FROM core.orders o WHERE o.order_id=n.order_id)')
            new_orders = cur.fetchone()[0]
            cur.execute('''SELECT count(*) FROM stage_orders n JOIN core.orders o USING(order_id)
                           WHERE n.order_status IS DISTINCT FROM o.status_code''')
            changed_statuses = cur.fetchone()[0]
            replace_model(cur, load_sql, checks_sql)
            summary = dict(model_summary(cur), new_orders=new_orders, changed_statuses=changed_statuses)
            version_id = uuid.uuid4().hex
            cur.execute('''INSERT INTO ops.dataset_versions
                           (version_id,dataset_sha256,transform_sha256,schema_sha256,source_id,sequence,
                            kind,archive_path,manifest,summary) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                        (version_id, dataset_hash, transform_hash, schema_hash, manifest['source_id'],
                         manifest['sequence'], manifest['kind'], str(archive), Json(manifest), Json(summary)))
            cur.execute('''INSERT INTO ops.current_dataset(singleton,version_id) VALUES (true,%s)
                           ON CONFLICT(singleton) DO UPDATE SET version_id=excluded.version_id''', (version_id,))
            finish_attempt(cur, attempt_id, 'published', version_id)
        # Данные, проверки, версия и указатель публикуются одним COMMIT.
        conn.commit()
        return dict(status='published', attempt_id=attempt_id, version_id=version_id, summary=summary)
    except Exception as error:
        conn.rollback()
        diagnostic = f'{type(error).__name__}: {error}'
        if isinstance(error, psycopg2.Error) and error.diag.table_name:
            diagnostic += f' [таблица={error.diag.table_name}, правило={error.diag.constraint_name}]'
        if received:
            with conn.cursor() as cur:
                # COMMIT мог завершиться, а подтверждение потеряться.
                cur.execute('SELECT status,version_id FROM ops.ingestion_attempts WHERE attempt_id=%s', (attempt_id,))
                recorded = cur.fetchone()
                if recorded and recorded[0] == 'published':
                    return dict(status='published', attempt_id=attempt_id, version_id=recorded[1], recovered=True)
                finish_attempt(cur, attempt_id, 'failed', error=diagnostic)
            conn.commit()
        return dict(status='failed', attempt_id=attempt_id, error=diagnostic)
    finally:
        # Закрытие соединения освобождает session advisory lock даже после ошибки/сигнала.
        conn.close()


def status(dbname=None):
    with connect(dbname) as conn, conn.cursor() as cur:
        current = current_version(cur)
        cur.execute("SELECT to_regclass('ops.ingestion_attempts')")
        attempts = []
        if cur.fetchone()[0]:
            cur.execute('SELECT to_jsonb(a) FROM ops.ingestion_attempts a ORDER BY started_at DESC LIMIT 20')
            attempts = [r[0] for r in cur.fetchall()]
    return dict(current=current, attempts=attempts)
