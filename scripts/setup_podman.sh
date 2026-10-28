#!/usr/bin/env bash
# Альтернативный запуск для Fedora/Podman, включая терминал Flatpak.
# Существующий контейнер и его данные не удаляются.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if command -v podman >/dev/null 2>&1; then
  ENGINE=(podman)
elif command -v flatpak-spawn >/dev/null 2>&1 && flatpak-spawn --host podman --version >/dev/null 2>&1; then
  ENGINE=(flatpak-spawn --host podman)
else
  echo 'Podman не найден. Для Docker используйте bash scripts/setup.sh.' >&2
  exit 1
fi
bash scripts/download_data.sh
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -c 'import psycopg2' 2>/dev/null || .venv/bin/python -m pip install psycopg2-binary
if "${ENGINE[@]}" container exists hack_postgres; then
  "${ENGINE[@]}" start hack_postgres >/dev/null
else
  "${ENGINE[@]}" run -d --name hack_postgres \
    -e POSTGRES_USER=hack -e POSTGRES_PASSWORD=hack -e POSTGRES_DB=marketplace \
    -e 'POSTGRES_INITDB_ARGS=--encoding=UTF8 --locale=C' \
    -p 127.0.0.1:5432:5432 \
    -v hackathon_students_pgdata:/var/lib/postgresql/data \
    docker.io/library/postgres:16-alpine
fi
ready=0
for ((attempt=0; attempt<60; attempt++)); do
  if "${ENGINE[@]}" exec hack_postgres pg_isready -U hack -d marketplace >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo 'PostgreSQL не запустился. Проверьте podman logs hack_postgres.' >&2
  exit 1
fi
.venv/bin/python scripts/load_raw.py
printf '\nПодключение: postgresql://hack:hack@localhost:5432/marketplace\n'
