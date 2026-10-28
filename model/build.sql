\set ON_ERROR_STOP on
-- Единственная точка сборки. Вход: подготовленный raw. При ошибке старый core/mart сохраняется.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';
SET LOCAL datestyle = 'ISO, YMD';
SELECT pg_advisory_xact_lock(72816301);
DROP SCHEMA IF EXISTS mart CASCADE;
DROP SCHEMA IF EXISTS core CASCADE;
CREATE SCHEMA core;
CREATE SCHEMA mart;
\ir schema.sql
\ir load.sql
\ir marts.sql
COMMIT;
ANALYZE core.orders;
ANALYZE core.order_items;
ANALYZE core.order_payments;
ANALYZE core.order_reviews;
