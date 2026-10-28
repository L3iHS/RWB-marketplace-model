"""Первые строки каждой таблицы и витрины, в виде таблиц pandas.

Запуск:
    docker compose run --rm app preview                 5 строк, схемы core и mart
    docker compose run --rm app preview -n 10           10 строк
    docker compose run --rm app preview -s raw          схема raw
    docker compose run --rm app preview -t orders       только таблицы, в имени которых есть 'orders'
    docker compose run --rm app preview --colwidth 40   шире колонки (длинные id не обрезаются)

Таблицы находятся автоматически через information_schema,
новые появятся в выводе без правки кода.
"""

import argparse
import shutil

import pandas as pd

from db import connect


def parse_args():
    parser = argparse.ArgumentParser(description="Первые строки таблиц в виде pandas")
    parser.add_argument("-n", type=int, default=5, help="сколько строк показать (по умолчанию 5)")
    parser.add_argument("-s", "--schemas", default="core,mart",
                        help="схемы через запятую (по умолчанию core,mart)")
    parser.add_argument("-t", "--table", default="", help="фильтр по имени таблицы")
    parser.add_argument("--colwidth", type=int, default=20,
                        help="максимальная ширина колонки, длиннее обрезается '...'")
    return parser.parse_args()


def list_tables(cur, schemas, name_filter):
    """Все таблицы и представления указанных схем, в порядке схем и имён."""
    cur.execute(
        """
        SELECT table_schema, table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = ANY(%s) AND table_name LIKE %s
        ORDER BY array_position(%s, table_schema::text), table_name
        """,
        (schemas, f"%{name_filter}%", schemas),
    )
    return cur.fetchall()


def read_head(cur, schema, table, n):
    """Первые n строк и общее число строк таблицы."""
    # Имена схемы и таблицы взяты из information_schema, а не от пользователя,
    # но всё равно экранируем их через двойные кавычки.
    full_name = f'"{schema}"."{table}"'
    cur.execute(f"SELECT count(*) FROM {full_name}")
    total = cur.fetchone()[0]
    cur.execute(f"SELECT * FROM {full_name} LIMIT %s", (n,))
    columns = [d.name for d in cur.description]
    # convert_dtypes: целые с пропусками остаются целыми (37, <NA>), а не 37.0 и NaN.
    df = pd.DataFrame(cur.fetchall(), columns=columns).convert_dtypes()
    return df, total


def main():
    args = parse_args()
    schemas = [s.strip() for s in args.schemas.split(",") if s.strip()]

    pd.set_option("display.width", shutil.get_terminal_size().columns)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.max_colwidth", args.colwidth)

    with connect() as conn, conn.cursor() as cur:
        tables = list_tables(cur, schemas, args.table)
        if not tables:
            print("Таблицы не найдены. Модель собрана? Запустите: docker compose run --rm app build")
            return

        for schema, table, table_type in tables:
            df, total = read_head(cur, schema, table, args.n)
            kind = "витрина (view)" if table_type == "VIEW" else "таблица"
            rows = f"{total:,}".replace(",", " ")
            print(f"\n=== {schema}.{table} — {kind}, {rows} строк × {len(df.columns)} колонок")
            # print(df), а не to_string(): так работают настройки ширины,
            # и широкие таблицы переносятся блоками, как в pandas.
            print(df if not df.empty else "(пусто)")


if __name__ == "__main__":
    main()
