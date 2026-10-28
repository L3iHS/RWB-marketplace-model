#!/usr/bin/env python3
"""Собрать модель из model/build.sql без установленного psql.

Важно для команды:
1. Python не рассчитывает выручку: вся бизнес-логика находится в SQL-файлах.
2. Порядок файлов берётся из build.sql, поэтому Python и psql делают одно и то же.
3. Все этапы выполняются в одной транзакции. COMMIT происходит только при
   успешном выходе из `with connection`; исключение приводит к ROLLBACK.
"""
import argparse
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / 'model'

# Эти названия только объясняют прогресс; порядок исполнения задаёт build.sql.
STAGE_DESCRIPTIONS = {
    '000_validate_raw.sql': 'Проверить типы, обязательные поля, ключи и связи источника',
    '001_schema.sql': 'Подготовить таблицы, ключи, ограничения и индексы core',
    '002_load.sql': 'Загрузить все сущности и сохранить постоянные ключи категорий',
    '003_marts.sql': 'Подготовить витрины заказов, продаж и предупреждений',
    '004_checks.sql': 'Сверить строки и суммы с источником, обновить статистику',
    '005_comments.sql': 'Добавить пояснения таблиц и полей для DBeaver',
}


def read_build_steps():
    """Прочитать build.sql и раскрыть локальные включения `\\ir` по порядку.

    `\\ir` и `\\set` — команды клиента psql, PostgreSQL их не понимает.
    BEGIN/COMMIT также не пересылаем: транзакцией здесь управляет psycopg2.
    Остальные строки SQL сохраняем, включая блокировки и их исходный порядок.
    """
    steps = []
    pending_lines = []

    def flush_pending():
        statement = '\n'.join(pending_lines).strip()
        if statement:
            steps.append(('build.sql: согласовать параллельные сборки и чтение raw', statement))
        pending_lines.clear()

    for line in (MODEL_DIR / 'build.sql').read_text(encoding='utf-8').splitlines():
        if line.startswith('\\ir '):
            flush_pending()
            source = (MODEL_DIR / line[4:]).resolve()
            # Включения разрешены только из каталога модели.
            source.relative_to(MODEL_DIR.resolve())
            description = STAGE_DESCRIPTIONS.get(source.name, source.name)
            steps.append((description, source.read_text(encoding='utf-8')))
        elif line.startswith('\\set ON_ERROR_STOP') or line in {'BEGIN;', 'COMMIT;'}:
            continue
        elif line.startswith('\\'):
            raise ValueError(f'Неизвестная команда psql: {line}')
        else:
            pending_lines.append(line)
    flush_pending()
    return steps


def read_build_sql():
    """Та же сборка одной строкой: используется тестами и упаковкой единого SQL."""
    return '\n\n'.join(statement for _, statement in read_build_steps())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn', default='postgresql://hack:hack@localhost:5432/marketplace')
    args = parser.parse_args()
    steps = read_build_steps()
    print('Все этапы — одна транзакция. Изменения фиксируются только после проверок.', flush=True)
    try:
        with psycopg2.connect(args.dsn) as connection:
            with connection.cursor() as cursor:
                for number, (description, statement) in enumerate(steps, start=1):
                    print(f'[{number}/{len(steps)}] {description}', flush=True)
                    cursor.execute(statement)
                cursor.execute('SELECT count(*) FROM core.orders')
                orders = cursor.fetchone()[0]
                cursor.execute('SELECT issue_code, count(*) FROM mart.quality_issues GROUP BY 1 ORDER BY 1')
                issues = cursor.fetchall()
        # До этой строки исключение откатывает все изменения текущей попытки.
    except psycopg2.Error as error:
        reason = error.diag.message_primary or str(error).strip()
        parser.exit(1, f'Сборка не выполнена: {reason}\nТранзакция не зафиксирована. Проверьте источник и повторите запуск.\n')
    print('Модель собрана, проверки пройдены, транзакция зафиксирована.')
    print('Заказы в core:', orders)
    for issue, count in issues:
        print(f'  {issue}: {count}')


if __name__ == '__main__':
    main()
