#!/usr/bin/env bash
# Собирает модель core и витрины mart из raw с нуля.
#
#   bash build.sh                 выполнить все model/*.sql по порядку
#   bash build.sh file.sql ...    выполнить только указанные файлы
#                                 (разведку, ответы на вопросы и т.п.)
#
# Все файлы выполняются одной транзакцией: при ошибке в любом месте
# изменения откатываются целиком, и в базе остаётся прежняя версия модели.
#
# Куда подключаемся:
#   по умолчанию — к сервису postgres из docker-compose.yml этого репозитория;
#   CONTAINER=hack_postgres bash build.sh  — к другому контейнеру (например,
#                                            из репозитория организаторов);
#   PGDATABASE=имя bash build.sh           — к другой базе (так делают тесты).
# SQL выполняется внутри контейнера, локальный psql не нужен.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

DB=${PGDATABASE:-marketplace}
if [ -n "${CONTAINER:-}" ]; then
  PSQL=(docker exec -i "$CONTAINER" psql)
else
  PSQL=(docker compose exec -T postgres psql)
fi

if [ $# -gt 0 ]; then
  FILES=("$@")
else
  FILES=(model/*.sql)
fi

echo "База: $DB. Файлы: ${FILES[*]}"

{
  echo 'BEGIN;'
  # Не ждать бесконечно, если таблицы заняты другим запросом,
  # и не дать зависшему запросу держать базу.
  echo "SET LOCAL lock_timeout = '5s';"
  echo "SET LOCAL statement_timeout = '120s';"
  # Даты в raw — в формате ГГГГ-ММ-ДД; фиксируем, чтобы разбор не зависел от настроек сервера.
  echo "SET LOCAL datestyle = 'ISO, YMD';"
  # Параллельные запросы берут разделяемую память, а Docker по умолчанию даёт
  # контейнеру лишь 64 МБ /dev/shm. На нашем объёме параллельность не нужна.
  echo "SET LOCAL max_parallel_workers_per_gather = 0;"
  for f in "${FILES[@]}"; do
    echo "\\echo '==> $f'"
    cat "$f"
    echo
  done
  echo 'COMMIT;'
} | "${PSQL[@]}" -U hack -d "$DB" -v ON_ERROR_STOP=1 -q -X

echo "Готово."
