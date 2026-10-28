-- Пересоздаём схемы core и mart с нуля, чтобы сборка всегда шла на чистом месте.
-- Схему raw не трогаем: это исходные данные.
-- Сборка идёт одной транзакцией (см. run.py): если что-то упадёт дальше,
-- удаление откатится и прежняя версия модели останется на месте.

-- Та же блокировка, что у регулярного загрузчика. Пересборка возвращает
-- модель к исходному raw и снимает указатель последующей публикации.
SELECT pg_advisory_xact_lock(72620261028);
DO $$ BEGIN
    IF to_regclass('ops.current_dataset') IS NOT NULL THEN
        DELETE FROM ops.current_dataset;
    END IF;
END $$;

DROP SCHEMA IF EXISTS mart CASCADE;
DROP SCHEMA IF EXISTS core CASCADE;
CREATE SCHEMA core;
CREATE SCHEMA mart;
