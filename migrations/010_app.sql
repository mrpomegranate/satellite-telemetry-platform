-- 010_app.sql  |  app schema: telemetry groups (owned by telemetry-platform)
--
-- A group is an analytical working set: a small, user-curated collection of
-- channels that may span subsystems. Distinct from the catalog hierarchy,
-- which is physical and ingest-owned. The tree is for finding; groups are for
-- working.
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.telem_group (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    satellite_id uuid NOT NULL REFERENCES catalog.satellite(id) ON DELETE CASCADE,
    name         text NOT NULL,
    description  text,
    owner_id     uuid,
    shared       boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (satellite_id, name)
);

CREATE TABLE IF NOT EXISTS app.group_member (
    group_id      uuid NOT NULL REFERENCES app.telem_group(id) ON DELETE CASCADE,
    channel_id    uuid NOT NULL REFERENCES catalog.channel(id) ON DELETE CASCADE,
    display_order smallint NOT NULL DEFAULT 0,
    axis          smallint NOT NULL DEFAULT 0,   -- 0 = left, 1 = right
    color         text,
    PRIMARY KEY (group_id, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_group_member_channel
    ON app.group_member (channel_id);
