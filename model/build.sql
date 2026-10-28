-- psql "postgresql://hack:hack@localhost:5432/marketplace" -f model/build.sql
-- Пересобирает данные только нашей модели; raw не меняет.
\set ON_ERROR_STOP on
BEGIN;
SELECT pg_advisory_xact_lock(682419035);
LOCK TABLE raw.orders, raw.order_items, raw.order_payments, raw.order_reviews,
           raw.products, raw.sellers, raw.customers, raw.product_category_translation IN SHARE MODE;
\ir 000_validate_raw.sql
\ir 001_schema.sql
\ir 002_load.sql
\ir 003_marts.sql
\ir 004_checks.sql
\ir 005_comments.sql
COMMIT;
