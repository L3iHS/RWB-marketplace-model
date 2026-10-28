# Образ для запуска проекта: Python с зависимостями и psql.
# Код в образ не копируется — docker-compose.yml монтирует репозиторий в /app,
# поэтому правки SQL и скриптов видны сразу, без пересборки образа.
# Пересобирать нужно только при изменении requirements.txt:
#   docker compose build app

FROM python:3.12-slim-bookworm

# psql — клиент PostgreSQL: им выполняются SQL-файлы сборки.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["python", "run.py"]
CMD ["--help"]
