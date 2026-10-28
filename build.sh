#!/usr/bin/env bash
# Собирает модель core и витрины mart из raw с нуля.
#
#   bash build.sh                 выполнить все model/*.sql по порядку
#   bash build.sh file.sql ...    выполнить только указанные файлы
#                                 (разведку, ответы на вопросы и т.п.)
#
# Все файлы выполняются одной транзакцией: при ошибке в любом месте
# изменения откатываются целиком, и в базе остаётся прежняя версия модели.
# SQL выполняется внутри контейнера, локальный psql не нужен.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

CONTAINER=${CONTAINER:-hack_postgres}

if [ $# -gt 0 ]; then
  FILES=("$@")
else
  FILES=(model/*.sql)
fi

echo "Файлы: ${FILES[*]}"

{
  echo 'BEGIN;'
  for f in "${FILES[@]}"; do
    echo "\\echo '==> $f'"
    cat "$f"
    echo
  done
  echo 'COMMIT;'
} | docker exec -i "$CONTAINER" \
      psql -U hack -d marketplace -v ON_ERROR_STOP=1 -q -X

echo "Готово."
