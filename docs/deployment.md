# Серверный запуск

Отдельный Compose для Ubuntu с Docker Engine и Compose v2+ находится в
`deploy/compose.yml`. Все команды ниже выполняются из корня репозитория.
Снаружи доступны только Caddy на TCP 80 и 443; PostgreSQL, API и nginx работают
в сети Compose. Лимиты памяти рассчитаны на демонстрационный сервер с 2 ГБ RAM.
CLI запускается отдельной командой и не включается в обычный `up`.

## Окружение и сборка

Порты 80 и 443 сервера должны быть свободны и доступны из интернета.
Для HTTPS направьте A-запись `y.cloud-path.ru` на `178.154.248.37`;
если есть AAAA-запись, она тоже должна вести на этот сервер.
До обновления DNS доступен HTTP по IP.

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
`APP_DOMAIN` и `APP_IP` можно изменить в этом файле. Не пересоздавайте `.env`
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

```bash
docker compose -f deploy/compose.yml --env-file deploy/.env up -d
docker compose -f deploy/compose.yml --env-file deploy/.env ps
curl --fail http://178.154.248.37/api/health
curl --fail http://178.154.248.37/api/demo/status
curl --fail https://y.cloud-path.ru/api/health
```

Ожидаемый ответ `/api/health`: `{"status":"ok"}`. После настройки DNS Caddy
получает и обновляет сертификат автоматически; до этого проверяйте HTTP по IP.
В браузере доступны `http://178.154.248.37` и `https://y.cloud-path.ru`.
При ошибке смотрите:

```bash
docker compose -f deploy/compose.yml --env-file deploy/.env logs --tail 100 backend caddy postgres
```

## Данные и перезапуск

PostgreSQL хранит обе базы и историю в named volume `rwb-marketplace_pgdata`.
Сертификаты Caddy сохраняются в `rwb-marketplace_caddy_data`, его настройки —
в `rwb-marketplace_caddy_config`. `data/` и `artifacts/runtime/` находятся на
сервере в репозитории и доступны контейнерам через bind mount.

`docker compose -f deploy/compose.yml --env-file deploy/.env down` сохраняет
volumes. Для обычного обновления достаточно пересобрать изменившиеся образы
и выполнить `up -d`. Не используйте `down -v`, `docker volume prune` и не удаляйте
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
