"""Отпечатки фактических данных и схемы БД для происхождения выгрузки."""
import hashlib
import json
from pathlib import Path
import uuid

from psycopg2 import sql


def hash_records(records):
    digest = hashlib.sha256()
    for record in records:
        value = json.dumps(record, ensure_ascii=False, default=str, separators=(',', ':')).encode('utf-8')
        digest.update(len(value).to_bytes(8, 'big'))
        digest.update(value)
    return digest.hexdigest()


def schema_fingerprint(conn, schema):
    """Читает строки потоком в стабильном порядке в транзакции вызывающего кода."""
    with conn.cursor() as cur:
        cur.execute('SELECT tablename FROM pg_tables WHERE schemaname = %s ORDER BY tablename', (schema,))
        names = [row[0] for row in cur.fetchall()]
    if not names:
        raise ValueError(f'Нет таблиц {schema}; сначала выполните setup и build')
    tables = {}
    for name in names:
        digest, count = hashlib.sha256(), 0
        with conn.cursor(name='fingerprint_' + uuid.uuid4().hex) as cur:
            cur.itersize = 2000
            cur.execute(sql.SQL('SELECT to_jsonb(t)::text FROM {}.{} t ORDER BY to_jsonb(t)::text')
                        .format(sql.Identifier(schema), sql.Identifier(name)))
            for (row,) in cur:
                value = row.encode('utf-8')
                digest.update(len(value).to_bytes(8, 'big'))
                digest.update(value)
                count += 1
        tables[name] = {'rows': count, 'sha256': digest.hexdigest()}
    return {'sha256': hash_records(tables.items()), 'tables': tables}


def model_schema_fingerprint(conn):
    """Ревизия реально созданных объектов, а не предполагаемо применённых SQL-файлов."""
    definitions = [
        ('columns', """SELECT table_schema, table_name, ordinal_position, column_name,
                              udt_schema, udt_name, is_nullable, column_default,
                              is_generated, generation_expression, character_maximum_length,
                              numeric_precision, numeric_scale, datetime_precision,
                              collation_schema, collation_name
                       FROM information_schema.columns WHERE table_schema IN ('core','mart')
                       ORDER BY table_schema, table_name, ordinal_position"""),
        ('constraints', """SELECT n.nspname, r.relname, c.conname, pg_get_constraintdef(c.oid, true)
                           FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid
                           JOIN pg_namespace n ON n.oid = r.relnamespace
                           WHERE n.nspname IN ('core','mart') ORDER BY 1,2,3"""),
        ('views', """SELECT schemaname, viewname, definition FROM pg_views
                     WHERE schemaname IN ('core','mart') ORDER BY 1,2"""),
        ('indexes', """SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes
                       WHERE schemaname IN ('core','mart') ORDER BY 1,2,3"""),
        ('functions', """SELECT n.nspname, p.proname, pg_get_functiondef(p.oid)
                         FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                         WHERE n.nspname IN ('core','mart') AND p.prokind IN ('f','p') ORDER BY 1,2,3"""),
    ]
    records = []
    with conn.cursor() as cur:
        for name, statement in definitions:
            cur.execute(statement)
            records.append((name, cur.fetchall()))
    return hash_records(records)


def collect_context(conn, root):
    model_files = sorted((Path(root) / 'model').glob('*.sql'))
    if not model_files:
        raise ValueError('Нет SQL-файлов модели для описания происхождения')
    return {
        'raw': schema_fingerprint(conn, 'raw'),
        'core': schema_fingerprint(conn, 'core'),
        'model_schema_sha256': model_schema_fingerprint(conn),
        # Файлы могут быть изменены без build: их хеш не выдаётся за ревизию самой БД.
        'workspace_model_sha256': hash_records(
            (p.relative_to(root).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest()) for p in model_files),
    }
