# Серверный запуск

Отдельный Compose для Ubuntu с Docker Engine и Compose v2+ находится в
`deploy/compose.yml`. Все команды ниже выполняются из корня репозитория.
PostgreSQL и API работают в сети Compose. Frontend доступен через отдельный
Caddy либо через существующий прокси сервера; собственные порты frontend не публикует.
Лимиты памяти рассчитаны на демонстрационный сервер с 2 ГБ RAM.
CLI запускается отдельной командой и не включается в обычный `up`.

## Окружение и сборка

Для HTTPS направьте A-запись `y.cloud-path.ru` на `178.154.248.37`;
если есть AAAA-запись, она тоже должна вести на этот сервер.

Создайте локальный файл с новым случайным паролем:

```bash
cp deploy/.env.example deploy/.env
chmod 600 deploy/.env
python3 - <<'PY'
from pathlib import Path
import secrets
path = Path('deploy/.env')
path.write_text(path.read_text().replace('POSTGRES_PASSWORD=\n',
                                       f'POSTGRES_PASSWORD={secrets.token_hex(32)}\n'))
PY
```

`.env` исключён из Git. Пустой пароль блокирует запуск Compose. Значения
`APP_DOMAIN` и `APP_IP` можно изменить в этом файле. Для существующего прокси
замените `EDGE_NETWORK=placeholder` именем Docker-сети, к которой подключён Caddy.
Не пересоздавайте `.env`
при обновлении существующей установки: пароль должен соответствовать БД.

```bash
docker compose -f deploy/compose.yml --env-file deploy/.env config --quiet
docker compose -f deploy/compose.yml --env-file deploy/.env build app backend frontend
docker compose -f deploy/compose.yml --env-file deploy/.env up -d postgres
docker compose -f deploy/compose.yml --env-file deploy/.env run --rm app setup
docker compose -f deploy/compose.yml --env-file deploy/.env run --rm app build
docker compose -f deploy/compose.yml --env-file deploy/.env run --rm app check
docker compose -f deploy/compose.yml --env-file deploy/.env run --rm app test
```

`setup` скачивает открытые CSV Olist в `data/` и загружает raw. `build`
пересобирает core и mart из raw; при обычном перезапуске эти команды не нужны.
На сервере с 2 ГБ памяти выполняйте первичную сборку и тесты до запуска API.

## Подготовка демонстрации

Чтобы первое нажатие кнопки не ожидало первичной сборки отдельной базы,
однократно подготовьте её до запуска сайта:

```bash
docker compose -f deploy/compose.yml --env-file deploy/.env run --rm app demo-init --database marketplace_demo_dashboard
```

Команда создаёт только новую БД; повторный запуск для существующей БД завершится
ошибкой и не пересоберёт её. В интерфейсе кнопка публикует по одному из пяти
синтетических снимков. Первая публикация также готовит файлы серии в
`artifacts/runtime/dashboard-demo/`. Состояние серии общее для посетителей.
Исходная база `marketplace` остаётся доступна отдельно. Планировщик не запускается.
API работает одним процессом, поскольку защита параллельного нажатия хранится
в памяти процесса.

## Запуск и проверка

### Через существующий Caddy

Используйте этот режим, когда порты 80/443 уже обслуживает другой проект.
Его Caddy и frontend нового приложения должны быть подключены к одной
существующей Docker-сети. Override подключает только frontend к сети
`EDGE_NETWORK` с alias `rwb-marketplace-ui`; PostgreSQL и API остаются в сети
этого проекта. Новый Caddy не запускается, дополнительные порты не открываются.

```bash
docker compose -f deploy/compose.yml -f deploy/compose.shared.yml --env-file deploy/.env config --quiet
docker compose -f deploy/compose.yml -f deploy/compose.shared.yml --env-file deploy/.env up -d
docker compose -f deploy/compose.yml -f deploy/compose.shared.yml --env-file deploy/.env ps
```

В конфигурацию существующего Caddy добавьте отдельный виртуальный хост,
сохраняя остальные сайты:

```caddyfile
y.cloud-path.ru {
    encode gzip
    reverse_proxy rwb-marketplace-ui:80
}
```

Проверьте конфигурацию средствами существующего Caddy и примените её штатным
reload. В этом режиме HTTP по IP остаётся под управлением существующего прокси;
проверяйте новый сайт по домену:

```bash
curl --fail https://y.cloud-path.ru/api/health
curl --fail https://y.cloud-path.ru/api/demo/status
```

### Отдельный сервер

Для выделенного сервера со свободными и доступными извне TCP 80/443 включите
профиль `standalone`. Он запускает Caddy с автоматическим HTTPS по домену
и HTTP по IP для проверки до обновления DNS.

```bash
docker compose -f deploy/compose.yml --env-file deploy/.env --profile standalone up -d
docker compose -f deploy/compose.yml --env-file deploy/.env --profile standalone ps
curl --fail http://178.154.248.37/api/health
curl --fail http://178.154.248.37/api/demo/status
curl --fail https://y.cloud-path.ru/api/health
```

Ожидаемый ответ `/api/health` для обоих режимов: `{"status":"ok"}`.
После настройки DNS Caddy получает и обновляет сертификат автоматически.
При ошибке приложения смотрите:

```bash
docker compose -f deploy/compose.yml --env-file deploy/.env logs --tail 100 backend postgres
```

Журнал прокси просматривайте в проекте существующего Caddy либо у сервиса
`caddy` с профилем `standalone`.

## Данные и перезапуск

PostgreSQL хранит обе базы и историю в named volume `rwb-marketplace_pgdata`.
В режиме `standalone` сертификаты Caddy сохраняются в `rwb-marketplace_caddy_data`, его настройки —
в `rwb-marketplace_caddy_config`. `data/` и `artifacts/runtime/` находятся на
сервере в репозитории и доступны контейнерам через bind mount.

`docker compose -f deploy/compose.yml --env-file deploy/.env down` сохраняет
volumes. Для обычного обновления достаточно пересобрать изменившиеся образы
и выполнить `up -d` с теми же файлами Compose и профилем, что при первом запуске.
В shared-режиме добавляйте `-f deploy/compose.shared.yml`, в отдельном —
`--profile standalone`. Не используйте `down -v`, `docker volume prune` и не удаляйте
каталоги `data/`, `artifacts/runtime/`: это удаляет данные или файлы демонстрации.
Сохраняйте имя проекта `rwb-marketplace`, чтобы после обновления подключались
те же volumes. Замена пароля в `.env` сама по себе не меняет пароль существующей БД.

Перед переносом или обновлением можно сохранить обе базы на сервере:

```bash
mkdir -p backups
chmod 700 backups
docker compose -f deploy/compose.yml --env-file deploy/.env exec -T postgres pg_dump -U hack -Fc marketplace > backups/marketplace.dump
docker compose -f deploy/compose.yml --env-file deploy/.env exec -T postgres pg_dump -U hack -Fc marketplace_demo_dashboard > backups/marketplace_demo_dashboard.dump
```

Храните дампы, `.env` и копии `data/`, `artifacts/runtime/` отдельно от рабочей
установки. Проверка наличия дампа не подтверждает проверку восстановления.
