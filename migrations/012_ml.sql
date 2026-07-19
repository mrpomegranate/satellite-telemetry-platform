-- 012_ml.sql  |  ml schema: registry, manifests, predictions, schedules
--
-- Scaffolded ahead of the services that use it so the retrain/signoff flow can
-- be built without another migration.
--
-- The keystone is `manifest`: a dataset version is a recipe, not a copy.
-- content_hash identifies it, ingest_watermark pins "data as of when",
-- transform_version versions the feature pipeline, parent_manifest chains
-- retrain lineage. Provenance for the ATO is then a recursive query.
CREATE SCHEMA IF NOT EXISTS ml;

DO $$ BEGIN
    CREATE TYPE ml.version_status AS ENUM
        ('candidate', 'promoted', 'retired');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS ml.manifest (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    content_hash      text NOT NULL UNIQUE,
    channel_ids       jsonb NOT NULL,
    time_ranges       jsonb NOT NULL,
    ingest_watermark  timestamptz NOT NULL,
    transform_version text NOT NULL DEFAULT 'v0',
    label_filter      jsonb NOT NULL DEFAULT '{}'::jsonb,
    parent_manifest   uuid REFERENCES ml.manifest(id),
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ml.model (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name       text NOT NULL UNIQUE,
    algorithm  text NOT NULL,
    impl_ref   text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ml.model_version (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id     uuid NOT NULL REFERENCES ml.model(id) ON DELETE CASCADE,
    version      integer NOT NULL,
    manifest_id  uuid REFERENCES ml.manifest(id),
    artifact_uri text,
    eval_metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    status       ml.version_status NOT NULL DEFAULT 'candidate',
    promoted_by  uuid,
    promoted_at  timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (model_id, version)
);

CREATE TABLE IF NOT EXISTS ml.model_group_binding (
    model_id   uuid NOT NULL REFERENCES ml.model(id) ON DELETE CASCADE,
    group_id   uuid NOT NULL REFERENCES app.telem_group(id) ON DELETE CASCADE,
    is_default boolean NOT NULL DEFAULT false,
    PRIMARY KEY (model_id, group_id)
);

CREATE TABLE IF NOT EXISTS ml.schedule (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id       uuid NOT NULL REFERENCES ml.model(id) ON DELETE CASCADE,
    group_id       uuid NOT NULL REFERENCES app.telem_group(id) ON DELETE CASCADE,
    cadence        text NOT NULL DEFAULT 'weekly',
    min_new_labels integer NOT NULL DEFAULT 5,
    enabled        boolean NOT NULL DEFAULT false,
    last_run       timestamptz,
    UNIQUE (model_id, group_id)
);

CREATE TABLE IF NOT EXISTS ml.prediction (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_version_id uuid NOT NULL REFERENCES ml.model_version(id) ON DELETE CASCADE,
    group_id         uuid NOT NULL REFERENCES app.telem_group(id) ON DELETE CASCADE,
    -- not named "window": that is a reserved word in Postgres
    window_range     tstzrange NOT NULL,
    regions          jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_prediction_group
    ON ml.prediction (group_id, created_at DESC);

-- Labels proposed by a model point back at the version that proposed them.
DO $$ BEGIN
    ALTER TABLE labels.label
        ADD CONSTRAINT label_proposed_by_version_fkey
        FOREIGN KEY (proposed_by_version)
        REFERENCES ml.model_version(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
