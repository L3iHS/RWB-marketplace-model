-- Пересоздаём схему core с нуля, чтобы сборка всегда шла на чистом месте.
-- Схему raw не трогаем: это исходные данные.

DROP SCHEMA IF EXISTS core CASCADE;
CREATE SCHEMA core;
