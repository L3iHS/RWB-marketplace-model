#!/usr/bin/env bash
# Подготовка отдельного окружения; повторный запуск не перезагружает raw.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 10), "Нужен Python 3.10+; укажите PYTHON=python3.13"'
command -v docker >/dev/null
docker info >/dev/null
if [[ ! -x .venv/bin/python ]]; then "$PYTHON" -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
bash scripts/download_data.sh
docker compose up -d postgres
ready=0
for _ in {1..30}; do
  if docker compose exec -T postgres pg_isready -U hack -d marketplace >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done
[[ "$ready" == 1 ]] || { echo 'База не готова; проверьте docker compose logs postgres'; exit 1; }
rows=$(docker compose exec -T postgres psql -U hack -d marketplace -Atqc 'SELECT count(*) FROM raw.orders')
if [[ "$rows" == 0 ]]; then
  .venv/bin/python scripts/load_raw.py --port "${PGPORT:-5433}"
else
  echo "raw уже содержит $rows заказов: исходники сохраняются."
fi
echo 'Окружение готово. Далее: make profile, make build, make check, make answers, make test.'
