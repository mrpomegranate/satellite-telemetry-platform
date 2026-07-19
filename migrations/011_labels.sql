-- 011_labels.sql  |  labels schema (owned by telemetry-platform)
--
-- Labels are first-class rows, not a separate database. A label attaches to a
-- group over a time range. Two classes are carried natively because satellite
-- operators draw the distinction:
--   off_nominal - a known, explainable departure (limit violation, expected event)
--   anomaly     - an unexplained deviation needing investigation
CREATE SCHEMA IF NOT EXISTS labels;

-- GiST needs btree_gist to combine a uuid column with a range column in one
-- index. Ships with Postgres as a standard extension.
CREATE EXTENSION IF NOT EXISTS btree_gist;

DO $$ BEGIN
    CREATE TYPE labels.label_class AS ENUM ('anomaly', 'off_nominal');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE labels.review_status AS ENUM
        ('proposed', 'accepted', 'rejected', 'missed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Controlled vocabulary for label types. Free text invites drift; a table
-- keeps the taxonomy maintainable and reportable.
CREATE TABLE IF NOT EXISTS labels.taxonomy (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    label_class labels.label_class NOT NULL,
    code        text NOT NULL UNIQUE,
    name        text NOT NULL,
    description text,
    color       text,
    active      boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS labels.label (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id      uuid NOT NULL REFERENCES app.telem_group(id) ON DELETE CASCADE,
    channel_id    uuid REFERENCES catalog.channel(id) ON DELETE CASCADE,
    time_range    tstzrange NOT NULL,
    label_class   labels.label_class NOT NULL,
    taxonomy_id   uuid REFERENCES labels.taxonomy(id),
    review_status labels.review_status NOT NULL DEFAULT 'accepted',
    note          text,
    author_id     uuid,
    -- null when a human drew it; set when a model proposed it
    proposed_by_version uuid,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_label_group_range
    ON labels.label USING gist (group_id, time_range);
CREATE INDEX IF NOT EXISTS idx_label_status
    ON labels.label (review_status, created_at DESC);

INSERT INTO labels.taxonomy (label_class, code, name, description, color) VALUES
    ('anomaly',     'unexplained_deviation', 'Unexplained deviation',
     'Behaviour departs from expectation with no known cause', '#993C1D'),
    ('anomaly',     'relationship_break',    'Relationship break',
     'Two channels that normally track each other diverged',   '#B4472A'),
    ('anomaly',     'step_change',           'Step change',
     'Abrupt level shift with no commanded cause',             '#8A3517'),
    ('off_nominal', 'limit_violation',       'Limit violation',
     'Value outside its configured operating limit',           '#BA7517'),
    ('off_nominal', 'expected_event',        'Expected event',
     'Known operational event such as eclipse or manoeuvre',   '#C9922E'),
    ('off_nominal', 'data_gap',              'Data gap',
     'Loss of signal or missing telemetry',                    '#8C7A5B')
ON CONFLICT (code) DO NOTHING;
