"""Подключение к локальной учебной базе; параметры совместимы с libpq."""
import os
import psycopg2


def connect(dbname=None):
    return psycopg2.connect(
        host=os.getenv('PGHOST', 'localhost'),
        port=os.getenv('PGPORT', '5433'),
        dbname=dbname or os.getenv('PGDATABASE', 'marketplace'),
        user=os.getenv('PGUSER', 'hack'),
        password=os.getenv('PGPASSWORD', 'hack'),
    )
