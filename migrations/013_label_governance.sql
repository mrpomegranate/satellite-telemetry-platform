-- 013_label_governance.sql  |  labels + app (owned by telemetry-platform)
--
-- Reshapes labelling around three ideas learned from the ESA Anomaly Detection
-- Benchmark (ESA-ADB), whose annotations come from ESOC operations engineers:
--
--   1. Three classes, not two. "nominal" must be explicit: a reviewed-clean
--      region is evidence, and absence of a label is not the same as normal.
--      ESA-ADB encodes exactly this as 0 = nominal, 1 = anomaly, 2 = rare event.
--
--   2. Class and type are independent. A reset caused by a telecommand is a
--      rare *nominal* event; an uncommanded reset is an *anomaly*. Same shape,
--      different class - the difference is context. So taxonomy entries declare
--      which classes they may carry rather than belonging to one.
--
--   3. Scope is univariate or multivariate. Some events implicate one channel;
--      others are about a relationship between several and belong to no single
--      channel.
--
-- Governance: labels start in the "working" tier where anyone may create them.
-- Only a steward promotes a label to "golden", and only golden labels feed
-- production training. Freedom at the edge, a gate before it matters.

-- ---------------------------------------------------------------------------
-- 1. Three-class enum
-- ---------------------------------------------------------------------------
-- ALTER TYPE ... ADD VALUE cannot be used later in the same transaction, and
-- this file runs as one statement, so the type is rebuilt instead.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum e
        JOIN pg_type t ON t.oid = e.enumtypid
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = 'labels' AND t.typname = 'label_class'
          AND e.enumlabel = 'nominal'
    ) THEN
        CREATE TYPE labels.label_class_new AS ENUM
            ('anomaly', 'off_nominal', 'nominal');

        ALTER TABLE labels.label
            ALTER COLUMN label_class TYPE labels.label_class_new
            USING label_class::text::labels.label_class_new;

        -- taxonomy stops owning a single class (see allowed_classes below)
        ALTER TABLE labels.taxonomy DROP COLUMN IF EXISTS label_class;

        DROP TYPE labels.label_class;
        ALTER TYPE labels.label_class_new RENAME TO label_class;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. Supporting enums
-- ---------------------------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE labels.label_scope AS ENUM ('channel', 'group');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    -- working: anyone may create and edit. golden: curated training truth.
    CREATE TYPE labels.label_tier AS ENUM ('working', 'golden');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE labels.label_source AS ENUM
        ('human', 'model', 'rule', 'imported');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE app.user_role AS ENUM ('viewer', 'analyst', 'steward', 'admin');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------------------------------------------------------------------------
-- 3. People and roles
-- ---------------------------------------------------------------------------
-- Stewards are the expert group: they govern the taxonomy and decide what
-- enters the golden set. Analysts label freely; nothing they do can corrupt
-- training data.
CREATE TABLE IF NOT EXISTS app.platform_user (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    username     text NOT NULL UNIQUE,
    display_name text,
    role         app.user_role NOT NULL DEFAULT 'analyst',
    active       boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 4. Taxonomy: independent of class, hierarchical, governed
-- ---------------------------------------------------------------------------
ALTER TABLE labels.taxonomy
    ADD COLUMN IF NOT EXISTS allowed_classes text[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS parent_code text,
    ADD COLUMN IF NOT EXISTS approved boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS proposed_by uuid REFERENCES app.platform_user(id),
    ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

DO $$ BEGIN
    ALTER TABLE labels.taxonomy
        ADD CONSTRAINT taxonomy_allowed_classes_nonempty
        CHECK (array_length(allowed_classes, 1) >= 1);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------------------------------------------------------------------------
-- 5. Label: scope, tier, source, provenance
-- ---------------------------------------------------------------------------
ALTER TABLE labels.label
    ADD COLUMN IF NOT EXISTS scope labels.label_scope NOT NULL DEFAULT 'channel',
    ADD COLUMN IF NOT EXISTS tier labels.label_tier NOT NULL DEFAULT 'working',
    ADD COLUMN IF NOT EXISTS source labels.label_source NOT NULL DEFAULT 'human',
    ADD COLUMN IF NOT EXISTS severity smallint,
    ADD COLUMN IF NOT EXISTS confidence real,
    ADD COLUMN IF NOT EXISTS origin_group_id uuid REFERENCES app.telem_group(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS promoted_by uuid REFERENCES app.platform_user(id),
    ADD COLUMN IF NOT EXISTS promoted_at timestamptz,
    ADD COLUMN IF NOT EXISTS external_id text;

-- The group a label was drawn in is context, not identity: a label made while
-- viewing one group must remain visible from any other view of the same
-- channels. group_id therefore becomes optional.
DO $$
BEGIN
    UPDATE labels.label SET origin_group_id = group_id
     WHERE origin_group_id IS NULL AND group_id IS NOT NULL;
    ALTER TABLE labels.label ALTER COLUMN group_id DROP NOT NULL;
EXCEPTION WHEN undefined_column THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS idx_label_tier
    ON labels.label (tier, review_status);
CREATE INDEX IF NOT EXISTS idx_label_external
    ON labels.label (external_id) WHERE external_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 6. Which channels a label implicates
-- ---------------------------------------------------------------------------
-- A relationship break involves several channels and is attributable to none
-- of them alone, so channels attach through a join table with a role.
CREATE TABLE IF NOT EXISTS labels.label_channel (
    label_id   uuid NOT NULL REFERENCES labels.label(id) ON DELETE CASCADE,
    channel_id uuid NOT NULL REFERENCES catalog.channel(id) ON DELETE CASCADE,
    role       text NOT NULL DEFAULT 'primary',
    PRIMARY KEY (label_id, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_label_channel_channel
    ON labels.label_channel (channel_id);

-- Backfill from the old single-channel column, then retire it.
INSERT INTO labels.label_channel (label_id, channel_id, role)
SELECT id, channel_id, 'primary'
FROM labels.label
WHERE channel_id IS NOT NULL
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 7. Taxonomy seed, following ESA-ADB's event classes
-- ---------------------------------------------------------------------------
-- allowed_classes carries the lesson: the same event type can be an anomaly or
-- an expected nominal event depending on whether it was commanded.
INSERT INTO labels.taxonomy (code, name, description, color, allowed_classes) VALUES
    ('point_anomaly',      'Point anomaly',
     'Single-sample departure from expected behaviour',
     '#993C1D', ARRAY['anomaly']),
    ('subsequence_anomaly','Subsequence anomaly',
     'Sustained departure over a window',
     '#B4472A', ARRAY['anomaly']),
    ('relationship_break', 'Relationship break',
     'Channels that normally track each other diverged',
     '#8A3517', ARRAY['anomaly']),
    ('step_change',        'Step change',
     'Abrupt level shift; anomalous unless commanded',
     '#A33F1E', ARRAY['anomaly', 'off_nominal']),
    ('drift',              'Drift',
     'Slow departure from baseline; degradation or ageing',
     '#8F4A2E', ARRAY['anomaly', 'off_nominal']),
    ('reset',              'Reset',
     'Subsystem reset; nominal when commanded, anomalous when not',
     '#B4472A', ARRAY['anomaly', 'off_nominal']),
    ('mode_transition',    'Mode transition',
     'Expected change of operating mode',
     '#BA7517', ARRAY['off_nominal']),
    ('limit_violation',    'Limit violation',
     'Value outside its configured operating limit',
     '#C9922E', ARRAY['off_nominal', 'anomaly']),
    ('communication_gap',  'Communication gap',
     'Loss of signal or missing telemetry',
     '#8C7A5B', ARRAY['off_nominal']),
    ('rare_nominal_event', 'Rare nominal event',
     'Unusual but expected and explainable behaviour',
     '#A08A5E', ARRAY['off_nominal']),
    ('reviewed_clean',     'Reviewed clean',
     'Inspected and confirmed normal - training evidence, not absence of a label',
     '#4F7A3A', ARRAY['nominal'])
ON CONFLICT (code) DO UPDATE
    SET name = EXCLUDED.name,
        description = EXCLUDED.description,
        color = EXCLUDED.color,
        allowed_classes = EXCLUDED.allowed_classes;

-- Retire seeds from 011 that the richer taxonomy replaces.
UPDATE labels.taxonomy SET active = false
 WHERE code IN ('unexplained_deviation', 'expected_event', 'data_gap')
   AND NOT EXISTS (SELECT 1 FROM labels.label l WHERE l.taxonomy_id = taxonomy.id);

-- ---------------------------------------------------------------------------
-- 8. The golden set as a view
-- ---------------------------------------------------------------------------
-- What production training reads. Only accepted, golden-tier labels qualify:
-- a model proposal never becomes training data without a human accepting it,
-- and a working label never leaks into production.
CREATE OR REPLACE VIEW labels.golden_label AS
SELECT l.id,
       l.time_range,
       l.label_class,
       t.code AS taxonomy_code,
       l.scope,
       l.severity,
       l.origin_group_id,
       l.promoted_at,
       -- array_remove keeps labels with no channel rows honest ({} not {NULL})
       array_remove(array_agg(lc.channel_id), NULL) AS channel_ids
FROM labels.label l
LEFT JOIN labels.taxonomy t ON t.id = l.taxonomy_id
LEFT JOIN labels.label_channel lc ON lc.label_id = l.id
WHERE l.tier = 'golden' AND l.review_status = 'accepted'
GROUP BY l.id, l.time_range, l.label_class, t.code, l.scope, l.severity,
         l.origin_group_id, l.promoted_at;