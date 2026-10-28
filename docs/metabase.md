# Metabase и PostgreSQL

Из корня репозитория:

```bash
docker compose up -d postgres metabase
docker compose ps
docker compose logs --tail=100 metabase
```

Открыть http://localhost:3000. Первый запуск может занять несколько минут.
Для существующего контейнера, созданного этим Compose, используется прежний
volume `pgdata`: сбрасывать базу не нужно. Если PostgreSQL запущен из другого
проекта, этот Compose не подключается к нему автоматически: сначала нужно
согласовать сеть и адрес, чтобы не запустить вторую базу на том же порту.

## Первое подключение

В мастере настройки Metabase создать свою учётную запись администратора.
Добавить источник PostgreSQL (при пропуске мастера — через администрирование баз):

| Поле | Значение |
|---|---|
| Отображаемое имя | Marketplace |
| Host / Сервер | `postgres` |
| Port / Порт | `5432` |
| Database / База | `marketplace` |
| Username / Пользователь | `hack` |
| Password / Пароль | `hack` |
| SSL | Выключен для этой локальной учебной базы |
| SSH tunnel | Выключен |

Сохранить подключение и дождаться синхронизации структуры. `localhost` здесь
не подходит: Metabase и PostgreSQL находятся в разных контейнерах.
Пароли в Compose предназначены для локального учебного окружения.

## Проверить витрины и собрать отчёт

В SQL-редакторе Metabase выбрать Marketplace и выполнить:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'mart'
ORDER BY table_name;
```

Витрины определены в `model/03_marts.sql`. Если список пуст, выполнить:

```bash
docker compose run --rm app setup
docker compose run --rm app build
docker compose run --rm app check
```

После создания витрин повторно синхронизировать структуру источника в Metabase.
Проверить, что в `mart.order_totals` одна строка на заказ, а `order_amount`
включает товары и доставку. Пример первого показателя:

```sql
SELECT SUM(goods_amount) AS turnover
FROM mart.order_totals
WHERE is_delivered = TRUE;
```

Выбрать визуализацию «Число», сохранить вопрос и добавить его на новый дашборд.
Остальные блоки:

| Блок | Источник и расчёт |
|---|---|
| Заказы | `order_totals`, `COUNT(*)`, фильтр `is_delivered = TRUE` |
| Средний чек | `order_totals`, `AVG(order_amount)`, тот же фильтр |
| Динамика | `order_totals`, группировка по месяцу `purchased_at` |
| Продавцы | `delivered_items`, `SUM(price)` по `seller_id` |
| Категории | `delivered_items`, `SUM(price)` по `category_id` |
| Качество данных | Таблица из `quality_issues` |

Для периода настроить фильтр дашборда и связать его с `purchased_at` каждого
продажного блока. Для SQL-вопросов потребуется параметр фильтра поля.
Блок качества не фильтровать по периоду без отдельного правила связи с заказами.
Для месяцев без продаж в SQL использовать календарь и LEFT JOIN.
HTML-макет остаётся образцом: он не загружается в Metabase автоматически.
Сам дашборд и подключение создаются в интерфейсе при первой настройке.

## Хранение и остановка

- `postgres` / volume `pgdata`: данные маркетплейса.
- `metabase-db` / volume `metabase_pgdata`: пользователи, вопросы, подключения и дашборды.
- `metabase`: интерфейс и выполнение запросов; доступен локально на порту 3000.

`MB_DB_*` задают служебную базу Metabase, а не источник аналитики.
Подключение к Marketplace сохраняется после настройки в интерфейсе.

```bash
docker compose stop
docker compose up -d postgres metabase
```

Эти команды сохраняют данные. `docker compose down` без `-v` также сохраняет
volumes. **`docker compose down -v` удаляют
обе базы, включая созданные дашборды.** Не использовать их для обычного запуска.

Metabase по умолчанию использует официальный образ `latest`. Для фиксации
проверенной версии задать `METABASE_IMAGE=metabase/metabase:<тег>` в `.env`.
Перед обновлением делать резервную копию служебной базы.

Документация: https://www.metabase.com/docs/latest/installation-and-operation/running-metabase-on-docker
