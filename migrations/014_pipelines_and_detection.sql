-- 014_pipelines_and_detection.sql  |  ml schema (owned by telemetry-platform)
--
-- Adds the machinery the training repo needs, while keeping schema ownership
-- in one place. `satellite-telemetry-mlflow` writes rows here but never
-- migrates.
--
-- Three ideas:
--
--   1. The job queue is a table. The platform API inserts a queued run; the
--      runner polls with FOR UPDATE SKIP LOCKED. No broker to deploy or
--      accredit, and the audit trail is a side effect rather than extra work.
--      Disconnected programs behave identically.
--
--   2. Node outputs cache by content hash, so re-running a graph skips
--      unchanged work. This only holds because pipeline notebooks declare
--      their inputs - the contract earns its keep here.
--
--   3. A model emits a number; a ruleset gives it meaning. Both are versioned,
--      so every auto-label traces to exactly two hashes.

-- ---------------------------------------------------------------------------
-- 1. Model task and fixed threshold
-- ---------------------------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE ml.model_task AS ENUM
        ('anomaly_detection', 'anomaly_classification', 'forecasting');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

ALTER TABLE ml.model
    ADD COLUMN IF NOT EXISTS task ml.model_task NOT NULL
        DEFAULT 'anomaly_detection',
    ADD COLUMN IF NOT EXISTS description text;

-- A promoted model must not depend on a within-window quantile at inference:
-- the decision boundary is learned once, at training time, and pinned here.
ALTER TABLE ml.model_version
    ADD COLUMN IF NOT EXISTS threshold double precision,
    ADD COLUMN IF NOT EXISTS threshold_method text,
    ADD COLUMN IF NOT EXISTS pipeline_run_id uuid;

CREATE INDEX IF NOT EXISTS idx_model_version_status
    ON ml.model_version (status, model_id);

-- ---------------------------------------------------------------------------
-- 2. Pipelines and the run queue
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ml.pipeline (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL UNIQUE,
    spec_uri    text NOT NULL,          -- path to the YAML graph, in git
    task        ml.model_task,
    description text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

DO $$ BEGIN
    CREATE TYPE ml.run_status AS ENUM
        ('queued', 'running', 'succeeded', 'failed', 'cancelled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS ml.pipeline_run (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id   uuid NOT NULL REFERENCES ml.pipeline(id) ON DELETE CASCADE,
    status        ml.run_status NOT NULL DEFAULT 'queued',
    params        jsonb NOT NULL DEFAULT '{}'::jsonb,
    manifest_id   uuid REFERENCES ml.manifest(id),
    requested_by  uuid,
    trigger       text NOT NULL DEFAULT 'manual',  -- manual | schedule | api
    queued_at     timestamptz NOT NULL DEFAULT now(),
    started_at    timestamptz,
    finished_at   timestamptz,
    error         text,
    log_uri       text,
    worker        text
);

-- The queue's hot path: oldest queued run first.
CREATE INDEX IF NOT EXISTS idx_pipeline_run_queue
    ON ml.pipeline_run (status, queued_at)
    WHERE status IN ('queued', 'running');

CREATE INDEX IF NOT EXISTS idx_pipeline_run_pipeline
    ON ml.pipeline_run (pipeline_id, queued_at DESC);

DO $$ BEGIN
    ALTER TABLE ml.model_version
        ADD CONSTRAINT model_version_pipeline_run_fkey
        FOREIGN KEY (pipeline_run_id)
        REFERENCES ml.pipeline_run(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------------------------------------------------------------------------
-- 3. Node output cache
-- ---------------------------------------------------------------------------
-- cache_key = hash(notebook_source, params, manifest_hash, upstream_hashes).
-- Change a training parameter and preprocessing is reused; edit a notebook and
-- everything downstream invalidates.
CREATE TABLE IF NOT EXISTS ml.node_output (
    cache_key       text PRIMARY KEY,
    pipeline_run_id uuid REFERENCES ml.pipeline_run(id) ON DELETE SET NULL,
    node_id         text NOT NULL,
    artifact_uri    text NOT NULL,
    content_hash    text,
    rows            bigint,
    bytes           bigint,
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_used_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_node_output_run
    ON ml.node_output (pipeline_run_id);

-- ---------------------------------------------------------------------------
-- 4. Forecasts
-- ---------------------------------------------------------------------------
-- Stored rather than recomputed: "expected 12.4 +/- 2.1, observed 19.8" is
-- only reconstructible if what was expected at the time was kept.
CREATE TABLE IF NOT EXISTS ml.forecast (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_version_id uuid NOT NULL REFERENCES ml.model_version(id) ON DELETE CASCADE,
    channel_id       uuid NOT NULL REFERENCES catalog.channel(id) ON DELETE CASCADE,
    issued_at        timestamptz NOT NULL,
    horizon          interval NOT NULL,
    bucket_seconds   integer NOT NULL,
    -- [{t, yhat, lo, hi}, ...]
    points           jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_forecast_channel
    ON ml.forecast (channel_id, issued_at DESC);

-- ---------------------------------------------------------------------------
-- 5. Rulesets
-- ---------------------------------------------------------------------------
-- Versioned because changing a rule changes what every future label means.
-- `rules` is a JSON DSL so edits are data, not code deploys.
CREATE TABLE IF NOT EXISTS ml.ruleset (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name         text NOT NULL,
    version      integer NOT NULL,
    content_hash text NOT NULL UNIQUE,
    rules        jsonb NOT NULL,
    active       boolean NOT NULL DEFAULT false,
    created_by   uuid,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

-- ---------------------------------------------------------------------------
-- 6. Detection runs
-- ---------------------------------------------------------------------------
-- Records exactly what ran over what window, so a rerun with a new ruleset
-- produces a comparable result instead of silently overwriting history.
CREATE TABLE IF NOT EXISTS ml.detection_run (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_version_id uuid REFERENCES ml.model_version(id) ON DELETE SET NULL,
    ruleset_id       uuid REFERENCES ml.ruleset(id) ON DELETE SET NULL,
    group_id         uuid REFERENCES app.telem_group(id) ON DELETE CASCADE,
    window_range     tstzrange NOT NULL,
    trigger          text NOT NULL DEFAULT 'manual',
    n_scored         integer,
    n_proposed       integer,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_detection_run_group
    ON ml.detection_run (group_id, created_at DESC);

-- Labels proposed by a detection run point back at it.
-- An auto label traces to exactly two hashes: the model version that scored
-- it and the ruleset version that classified it.
ALTER TABLE labels.label
    ADD COLUMN IF NOT EXISTS detection_run_id uuid,
    ADD COLUMN IF NOT EXISTS ruleset_id uuid;

DO $$ BEGIN
    ALTER TABLE labels.label
        ADD CONSTRAINT label_detection_run_fkey
        FOREIGN KEY (detection_run_id)
        REFERENCES ml.detection_run(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE labels.label
        ADD CONSTRAINT label_ruleset_fkey
        FOREIGN KEY (ruleset_id)
        REFERENCES ml.ruleset(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------------------------------------------------------------------------
-- 7. LLM audit log
-- ---------------------------------------------------------------------------
-- Local to each program. Central LLM logs live outside this accreditation
-- boundary, and disconnected programs have none at all, so this is the source
-- of truth either way.
CREATE TABLE IF NOT EXISTS ml.llm_call (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid,
    provider      text NOT NULL,
    model         text NOT NULL,
    model_version text,
    purpose       text,
    context       jsonb NOT NULL DEFAULT '{}'::jsonb,
    prompt        text NOT NULL,
    response      text,
    tool_calls    jsonb,
    tokens_in     integer,
    tokens_out    integer,
    latency_ms    integer,
    error         text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_llm_call_created
    ON ml.llm_call (created_at DESC);

-- ---------------------------------------------------------------------------
-- 8. Views
-- ---------------------------------------------------------------------------
-- What the production model picker reads.
CREATE OR REPLACE VIEW ml.production_model AS
SELECT m.id            AS model_id,
       m.name,
       m.task,
       v.id            AS version_id,
       v.version,
       v.threshold,
       v.eval_metrics,
       v.promoted_at,
       man.content_hash AS manifest_hash,
       b.group_id
FROM ml.model m
JOIN ml.model_version v ON v.model_id = m.id AND v.status = 'promoted'
LEFT JOIN ml.manifest man ON man.id = v.manifest_id
LEFT JOIN ml.model_group_binding b ON b.model_id = m.id;

-- Queue depth at a glance.
CREATE OR REPLACE VIEW ml.run_queue AS
SELECT r.id, p.name AS pipeline, r.status, r.trigger, r.queued_at,
       r.started_at, r.finished_at, r.error
FROM ml.pipeline_run r
JOIN ml.pipeline p ON p.id = r.pipeline_id
ORDER BY r.queued_at DESC;