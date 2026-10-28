-- Пересоздаём схемы core и mart с нуля, чтобы сборка всегда шла на чистом месте.
-- Схему raw не трогаем: это исходные данные.
-- Сборка идёт одной транзакцией (см. run.py): если что-то упадёт дальше,
-- удаление откатится и прежняя версия модели останется на месте.

DROP SCHEMA IF EXISTS mart CASCADE;
DROP SCHEMA IF EXISTS core CASCADE;
CREATE SCHEMA core;
CREATE SCHEMA mart;
