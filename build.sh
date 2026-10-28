#!/usr/bin/env bash
# Собирает модель core из raw с нуля.
#
#   bash build.sh                 выполнить все model/*.sql по порядку
#   bash build.sh file.sql ...    выполнить только указанные файлы
#
# SQL выполняется внутри контейнера hack_postgres, локальный psql не нужен.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

CONTAINER=${CONTAINER:-hack_postgres}

if [ $# -gt 0 ]; then
  FILES=("$@")
else
  FILES=(model/*.sql)
fi

for f in "${FILES[@]}"; do
  echo "==> $f"
  docker exec -i "$CONTAINER" \
    psql -U hack -d marketplace -v ON_ERROR_STOP=1 -q -X < "$f"
done

echo "Готово."
