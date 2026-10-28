#!/usr/bin/env python3
"""Интеграционные проверки на текущем снимке Olist.
Выполняет две полные сборки и проверяет откат намеренной ошибки в третьей.
Запуск: .venv/bin/python scripts/check_model.py
"""
import argparse
from decimal import Decimal
import psycopg2
from psycopg2 import sql
from build_model import ROOT, read_build_sql


def fingerprint(cur, schema):
    cur.execute('SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename', (schema,))
    tables = [row[0] for row in cur.fetchall()]
    result = {}
    for table in tables:
        # Включает все колонки и повторения строк; порядок хранения не влияет.
        cur.execute(sql.SQL('SELECT count(*), md5(string_agg(to_jsonb(t)::text, chr(10) ORDER BY to_jsonb(t)::text)) FROM {}.{} t').format(sql.Identifier(schema), sql.Identifier(table)))
        result[table] = cur.fetchone()
    return result


def check_answers(cur):
    results = {}
    for path in sorted((ROOT / 'model/queries').glob('*.sql')):
        cur.execute(path.read_text(encoding='utf-8'))
        results[path.name[:2]] = cur.fetchall()
    monthly = results['01']
    assert len(monthly) == 24
    assert sum(row[2] for row in monthly) == Decimal('13221498.11')
    assert [(str(row[0]),row[1]) for row in monthly if row[2]==0] == [('2016-11-01',0)]
    assert len(results['02']) == 10 and results['02'][0][-1] == Decimal('226987.93')
    assert results['03'] == [(Decimal('159.88'), Decimal('1.0385'), Decimal('1.1422'))]
    assert results['04'] == [(96096, 2997, Decimal('3.12'))]
    categories = results['05']
    assert len(categories) == 74
    assert categories[0][2] == Decimal('1233131.72')
    assert sum(row[2] for row in categories) == Decimal('13221498.11')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn', default='postgresql://hack:hack@localhost:5432/marketplace')
    args = parser.parse_args()
    build = read_build_sql()
    conn = psycopg2.connect(args.dsn)
    try:
        with conn.cursor() as cur:
            raw_before = fingerprint(cur, 'raw')
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(build)
            check_answers(cur)
            first = fingerprint(cur, 'core')
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(build)
            check_answers(cur)
            assert fingerprint(cur, 'core') == first, 'Повторная сборка изменила модель'
        conn.commit()
        print('Две сборки идентичны; все пять контрольных ответов сошлись.')
        try:
            with conn.cursor() as cur:
                cur.execute(build)
                cur.execute('SELECT 1 / 0')  # Ошибка после обновления всех таблиц.
        except psycopg2.errors.DivisionByZero:
            conn.rollback()
        else:
            raise AssertionError('Не удалось вызвать проверочную ошибку')
        with conn.cursor() as cur:
            assert fingerprint(cur, 'core') == first, 'Откат не восстановил модель'
            assert fingerprint(cur, 'raw') == raw_before, 'Исходные данные изменились'
            check_answers(cur)
        conn.commit()
        print('Ошибка откатилась; предыдущая модель и исходные raw сохранены.')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
