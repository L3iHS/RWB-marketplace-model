-- Служебная история приёма; core/mart остаются бизнес-моделью.
CREATE SCHEMA IF NOT EXISTS ops;
CREATE TABLE IF NOT EXISTS ops.dataset_versions (
    version_id text PRIMARY KEY,
    dataset_sha256 text NOT NULL,
    transform_sha256 text NOT NULL,
    schema_sha256 text NOT NULL,
    source_id text NOT NULL,
    sequence bigint NOT NULL CHECK (sequence > 0),
    kind text NOT NULL CHECK (kind IN ('synthetic','external')),
    archive_path text NOT NULL,
    manifest jsonb NOT NULL,
    summary jsonb NOT NULL,
    published_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (dataset_sha256, transform_sha256, schema_sha256)
);
CREATE TABLE IF NOT EXISTS ops.current_dataset (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    version_id text NOT NULL REFERENCES ops.dataset_versions
);
CREATE TABLE IF NOT EXISTS ops.ingestion_attempts (
    attempt_id text PRIMARY KEY,
    input_path text NOT NULL,
    input_signature text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    status text NOT NULL CHECK (status IN ('received','validating','publishing','published','failed','skipped','stale_batch')),
    version_id text REFERENCES ops.dataset_versions,
    archive_path text,
    error text
);
