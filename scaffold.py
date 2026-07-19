#!/usr/bin/env python3
"""Scaffold the `telemetry-platform` repository.

The application side of the analytics platform. Owns the `app`, `labels` and
`ml` schemas in the same per-program database that `telemetry-db` created, plus
the API services and the React UI.

Foreign keys cross one way only: platform -> catalog. Run telemetry-db's
migrations first; this repo's migrations are numbered from 010 so ordering is
obvious when both are applied to one database.

Usage:
    python scaffold_platform.py                 # scaffold into current directory
    python scaffold_platform.py --root myrepo   # scaffold into ./myrepo
    python scaffold_platform.py --force         # overwrite existing files
"""
import argparse
import os
import stat

FILES = {}

# ---------------------------------------------------------------------------
# Top level
# ---------------------------------------------------------------------------

FILES["README.md"] = '''# telemetry-platform

Visualization, labeling and prediction platform for satellite telemetry.
Companion to `telemetry-db`, which owns the `catalog` and `telemetry` schemas.

## Boundary

| Repo | Schemas | Contents |
|------|---------|----------|
| `telemetry-db` | `catalog`, `telemetry` | satellites, subsystems, channels, samples |
| `telemetry-platform` (this) | `app`, `labels`, `ml` | groups, labels, models, manifests |

Foreign keys point **platform -> catalog** and never the other way. Apply
`telemetry-db` migrations (001-004) before this repo's (010+).

## Stack

- FastAPI + psycopg (async pool) against Postgres/TimescaleDB
- React + TypeScript + Vite, charts by Apache ECharts
- uv for Python deps, npm for the web app

## Quickstart

Assumes `telemetry-db` is already up with GOCE data ingested.

```bash
cp .env.example .env
uv sync
make migrate          # apply 010-012 to the same database
make api              # http://localhost:8000/docs
cd web && npm install && npm run dev    # http://localhost:5173
```

## Resolution switching

The chart never receives more than a few thousand points. `/timeseries` picks
the coarsest tier that still resolves the requested window:

| Window | Tier | Source |
|--------|------|--------|
| months - years | 6h buckets | `telemetry.sample_stats` (21600) |
| days - weeks | 10min buckets | `telemetry.sample_stats` (600) |
| minutes - hours | raw samples | `telemetry.sample` |

Aggregate tiers carry min/q05/mean/q95/max, so the UI draws an envelope band
rather than a bare mean line.

## v1 scope

Navigation (tree + channel finder + groups), visualization (multi-channel
charts, envelope shading, brush select, resolution switching), and labeling
(region and point labels, anomaly vs off-nominal, review status).

The `ml` schema and registry endpoints are scaffolded but intentionally thin:
models, manifests, bindings and schedules exist as tables and stubs so the
retrain/signoff flow can be built without a migration later.
'''

FILES[".gitignore"] = '''__pycache__/
*.pyc
.env
.venv/
.pytest_cache/
.ruff_cache/
vendor/
requirements.lock

# web
web/node_modules/
web/dist/
web/.vite/

# uv.lock is intentionally NOT ignored - commit it.
'''

FILES[".env.example"] = '''# Same database that telemetry-db provisioned, one per program.
DATABASE_URL=postgresql://telemetry:telemetry@localhost:5432/esa

API_HOST=0.0.0.0
API_PORT=8000

# Comma-separated origins allowed to call the API.
CORS_ORIGINS=http://localhost:5173

# Max points returned per channel per request; drives tier selection.
MAX_POINTS=2000
'''

FILES[".python-version"] = '''3.12
'''

FILES["pyproject.toml"] = '''[project]
name = "telemetry-platform"
version = "0.1.0"
description = "Visualization, labeling and prediction platform for satellite telemetry"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "psycopg[binary,pool]>=3.2",
    "pydantic>=2.9",
    "python-dotenv>=1.0",
]

[dependency-groups]
dev = [
    "pytest>=8",
    "httpx>=0.27",
    "ruff>=0.6",
]

[tool.uv]
package = false

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.pytest.ini_options]
testpaths = ["tests"]
'''

FILES["docker-compose.yml"] = '''# The database itself lives in the telemetry-db repo. This compose file runs
# the platform services against it, joining that repo's network.
services:
  api:
    build:
      context: .
      dockerfile: docker/api/Dockerfile
    environment:
      DATABASE_URL: ${DATABASE_URL:-postgresql://telemetry:telemetry@telemetry-db:5432/esa}
      CORS_ORIGINS: ${CORS_ORIGINS:-http://localhost:5173}
      MAX_POINTS: ${MAX_POINTS:-2000}
    ports:
      - "${API_PORT:-8000}:8000"
    volumes:
      - ./api:/app/api:ro
    networks:
      - telemetry

  migrate:
    build:
      context: .
      dockerfile: docker/api/Dockerfile
    entrypoint: ["python", "-m", "api.migrate"]
    environment:
      DATABASE_URL: ${DATABASE_URL:-postgresql://telemetry:telemetry@telemetry-db:5432/esa}
    volumes:
      - ./migrations:/app/migrations:ro
    networks:
      - telemetry
    profiles: ["tools"]

networks:
  telemetry:
    external: true
    name: ${TELEMETRY_NETWORK:-satellite-telemetry-db_default}
'''

# ---------------------------------------------------------------------------
# Migrations - numbered from 010 to sit after telemetry-db's 001-004
# ---------------------------------------------------------------------------

FILES["migrations/010_app.sql"] = '''-- 010_app.sql  |  app schema: telemetry groups (owned by telemetry-platform)
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
'''

FILES["migrations/011_labels.sql"] = '''-- 011_labels.sql  |  labels schema (owned by telemetry-platform)
--
-- Labels are first-class rows, not a separate database. A label attaches to a
-- group over a time range. Two classes are carried natively because satellite
-- operators draw the distinction:
--   off_nominal - a known, explainable departure (limit violation, expected event)
--   anomaly     - an unexplained deviation needing investigation
CREATE SCHEMA IF NOT EXISTS labels;

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
'''

FILES["migrations/012_ml.sql"] = '''-- 012_ml.sql  |  ml schema: registry, manifests, predictions, schedules
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
'''

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

FILES["api/__init__.py"] = '''# telemetry-platform API
'''

FILES["api/config.py"] = '''"""Runtime configuration from the environment."""
import os


def database_url() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql://telemetry:telemetry@localhost:5432/esa"
    )


def cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "http://localhost:5173")
    return [o.strip() for o in raw.split(",") if o.strip()]


def max_points() -> int:
    return int(os.environ.get("MAX_POINTS", "2000"))
'''

FILES["api/db.py"] = '''"""Async connection pool shared by the routers."""
from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import database_url

_pool: AsyncConnectionPool | None = None


async def open_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            database_url(), min_size=1, max_size=10, open=False,
            kwargs={"row_factory": dict_row},
        )
        await _pool.open()
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("pool not open")
    return _pool


async def fetch_all(sql: str, params: tuple = ()) -> list[dict]:
    async with pool().connection() as conn, conn.cursor() as cur:
        await cur.execute(sql, params)
        return await cur.fetchall()


async def fetch_one(sql: str, params: tuple = ()) -> dict | None:
    async with pool().connection() as conn, conn.cursor() as cur:
        await cur.execute(sql, params)
        return await cur.fetchone()


async def execute(sql: str, params: tuple = ()) -> None:
    async with pool().connection() as conn, conn.cursor() as cur:
        await cur.execute(sql, params)
'''

FILES["api/schemas.py"] = '''"""Pydantic request/response models."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field


class Satellite(BaseModel):
    id: uuid.UUID
    designator: str
    bus_design: str | None = None
    launch_date: dt.date | None = None


class Subsystem(BaseModel):
    id: uuid.UUID
    satellite_id: uuid.UUID
    code: str
    name: str | None = None
    channel_count: int | None = None


class Channel(BaseModel):
    id: uuid.UUID
    subsystem_id: uuid.UUID
    subsystem_code: str | None = None
    mnemonic: str
    display_name: str | None = None
    units: str | None = None
    sample_rate: str | None = None


class Point(BaseModel):
    """One rendered point. Envelope fields are null for the raw tier."""

    t: dt.datetime
    v: float | None = None
    lo: float | None = None
    hi: float | None = None
    p05: float | None = None
    p95: float | None = None


class Series(BaseModel):
    channel_id: uuid.UUID
    mnemonic: str
    units: str | None = None
    tier: str
    bucket_seconds: int | None = None
    points: list[Point]


class TimeseriesResponse(BaseModel):
    start: dt.datetime
    end: dt.datetime
    tier: str
    series: list[Series]


class GroupCreate(BaseModel):
    satellite_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    channel_ids: list[uuid.UUID] = []


class GroupMember(BaseModel):
    channel_id: uuid.UUID
    mnemonic: str
    units: str | None = None
    display_order: int = 0
    axis: int = 0


class Group(BaseModel):
    id: uuid.UUID
    satellite_id: uuid.UUID
    name: str
    description: str | None = None
    members: list[GroupMember] = []


class LabelCreate(BaseModel):
    group_id: uuid.UUID
    start: dt.datetime
    end: dt.datetime
    label_class: str = Field(pattern="^(anomaly|off_nominal)$")
    taxonomy_code: str | None = None
    channel_id: uuid.UUID | None = None
    note: str | None = None
    review_status: str = "accepted"


class Label(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    channel_id: uuid.UUID | None = None
    start: dt.datetime
    end: dt.datetime
    label_class: str
    taxonomy_code: str | None = None
    taxonomy_name: str | None = None
    color: str | None = None
    review_status: str
    note: str | None = None
    created_at: dt.datetime


class TaxonomyItem(BaseModel):
    id: uuid.UUID
    label_class: str
    code: str
    name: str
    description: str | None = None
    color: str | None = None
'''

FILES["api/tiers.py"] = '''"""Resolution selection.

The browser never receives more than `max_points` per channel. Given a window,
pick the finest tier that still fits, then read the matching table. This is why
the chart stays fast without WASM: the point count is capped server-side
regardless of how much data exists.
"""
from __future__ import annotations

import datetime as dt

# (bucket seconds, tier name). None bucket = raw samples.
TIERS: list[tuple[int | None, str]] = [
    (None, "raw"),
    (600, "10min"),
    (21600, "6h"),
]

RAW_ASSUMED_SECONDS = 1


def pick_tier(start: dt.datetime, end: dt.datetime, max_points: int) -> tuple[int | None, str]:
    """Finest tier whose point count fits the budget; coarsest as fallback."""
    span = max((end - start).total_seconds(), 1.0)
    for bucket, name in TIERS:
        effective = bucket or RAW_ASSUMED_SECONDS
        if span / effective <= max_points:
            return bucket, name
    return TIERS[-1]
'''

FILES["api/routers/__init__.py"] = '''# routers
'''

FILES["api/routers/catalog.py"] = '''"""Catalog navigation: satellites, subsystems, channel search.

Read-only. The catalog is owned by the telemetry-db repo; the platform only
reads it. The tree deliberately stops at subsystem - with thousands of channels
per satellite, the fourth level is a search problem, not a tree problem.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from ..db import fetch_all
from ..schemas import Channel, Satellite, Subsystem

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/satellites", response_model=list[Satellite])
async def list_satellites():
    return await fetch_all(
        "SELECT id, designator, bus_design, launch_date "
        "FROM catalog.satellite ORDER BY designator"
    )


@router.get("/satellites/{satellite_id}/subsystems", response_model=list[Subsystem])
async def list_subsystems(satellite_id: uuid.UUID):
    return await fetch_all(
        """
        SELECT s.id, s.satellite_id, s.code, s.name,
               count(c.id)::int AS channel_count
        FROM catalog.subsystem s
        LEFT JOIN catalog.channel c ON c.subsystem_id = s.id
        WHERE s.satellite_id = %s
        GROUP BY s.id, s.satellite_id, s.code, s.name
        ORDER BY s.code
        """,
        (satellite_id,),
    )


@router.get("/channels", response_model=list[Channel])
async def search_channels(
    q: str | None = Query(None, description="substring of mnemonic or display name"),
    satellite_id: uuid.UUID | None = None,
    subsystem_id: uuid.UUID | None = None,
    limit: int = Query(50, le=500),
):
    where = []
    params: list = []
    if satellite_id:
        where.append("sub.satellite_id = %s")
        params.append(satellite_id)
    if subsystem_id:
        where.append("c.subsystem_id = %s")
        params.append(subsystem_id)
    if q:
        where.append("(c.mnemonic ILIKE %s OR c.display_name ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    return await fetch_all(
        f"""
        SELECT c.id, c.subsystem_id, sub.code AS subsystem_code,
               c.mnemonic, c.display_name, c.units, c.sample_rate
        FROM catalog.channel c
        JOIN catalog.subsystem sub ON sub.id = c.subsystem_id
        {clause}
        ORDER BY c.mnemonic
        LIMIT %s
        """,
        tuple(params),
    )
'''

FILES["api/routers/timeseries.py"] = '''"""Windowed telemetry reads with automatic resolution switching."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException, Query

from ..config import max_points
from ..db import fetch_all
from ..schemas import Series, TimeseriesResponse
from ..tiers import pick_tier

router = APIRouter(prefix="/timeseries", tags=["timeseries"])

STATS_SQL = """
SELECT ss.bucket AS t,
       ss.value_mean AS v,
       ss.value_min  AS lo,
       ss.value_max  AS hi,
       ss.value_q05  AS p05,
       ss.value_q95  AS p95
FROM telemetry.sample_stats ss
WHERE ss.channel_id = %s
  AND ss.bucket_seconds = %s
  AND ss.bucket >= %s AND ss.bucket < %s
ORDER BY ss.bucket
"""

RAW_SQL = """
SELECT s.ts AS t, s.value AS v,
       NULL::double precision AS lo, NULL::double precision AS hi,
       NULL::double precision AS p05, NULL::double precision AS p95
FROM telemetry.sample s
WHERE s.channel_id = %s
  AND s.ts >= %s AND s.ts < %s
ORDER BY s.ts
"""


@router.get("", response_model=TimeseriesResponse)
async def read_timeseries(
    channel_ids: list[uuid.UUID] = Query(..., description="repeat for each channel"),
    start: dt.datetime = Query(...),
    end: dt.datetime = Query(...),
    tier: str | None = Query(None, description="force a tier: raw | 10min | 6h"),
):
    if end <= start:
        raise HTTPException(400, "end must be after start")
    if not channel_ids:
        raise HTTPException(400, "at least one channel_id required")

    budget = max_points()
    if tier:
        lookup = {"raw": None, "10min": 600, "6h": 21600}
        if tier not in lookup:
            raise HTTPException(400, f"unknown tier {tier!r}")
        bucket, tier_name = lookup[tier], tier
    else:
        bucket, tier_name = pick_tier(start, end, budget)

    series: list[Series] = []
    for channel_id in channel_ids:
        meta = await fetch_all(
            "SELECT mnemonic, units FROM catalog.channel WHERE id = %s", (channel_id,)
        )
        if not meta:
            raise HTTPException(404, f"channel {channel_id} not found")

        if bucket is None:
            rows = await fetch_all(RAW_SQL, (channel_id, start, end))
        else:
            rows = await fetch_all(STATS_SQL, (channel_id, bucket, start, end))

        series.append(
            Series(
                channel_id=channel_id,
                mnemonic=meta[0]["mnemonic"],
                units=meta[0]["units"],
                tier=tier_name,
                bucket_seconds=bucket,
                points=rows,
            )
        )

    return TimeseriesResponse(start=start, end=end, tier=tier_name, series=series)


@router.get("/extent")
async def channel_extent(channel_id: uuid.UUID):
    """Earliest and latest bucket available, so the UI can frame a first view."""
    rows = await fetch_all(
        """
        SELECT min(bucket) AS first, max(bucket) AS last, count(*)::bigint AS n
        FROM telemetry.sample_stats WHERE channel_id = %s
        """,
        (channel_id,),
    )
    return rows[0] if rows else {"first": None, "last": None, "n": 0}
'''

FILES["api/routers/groups.py"] = '''"""Telemetry groups: the analytical working set."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from ..db import execute, fetch_all, fetch_one
from ..schemas import Group, GroupCreate

router = APIRouter(prefix="/groups", tags=["groups"])


async def _members(group_id: uuid.UUID) -> list[dict]:
    return await fetch_all(
        """
        SELECT gm.channel_id, c.mnemonic, c.units, gm.display_order, gm.axis
        FROM app.group_member gm
        JOIN catalog.channel c ON c.id = gm.channel_id
        WHERE gm.group_id = %s
        ORDER BY gm.display_order, c.mnemonic
        """,
        (group_id,),
    )


@router.get("", response_model=list[Group])
async def list_groups(satellite_id: uuid.UUID | None = None):
    if satellite_id:
        rows = await fetch_all(
            "SELECT id, satellite_id, name, description FROM app.telem_group "
            "WHERE satellite_id = %s ORDER BY name",
            (satellite_id,),
        )
    else:
        rows = await fetch_all(
            "SELECT id, satellite_id, name, description FROM app.telem_group ORDER BY name"
        )
    return [Group(**row, members=await _members(row["id"])) for row in rows]


@router.post("", response_model=Group, status_code=201)
async def create_group(payload: GroupCreate):
    row = await fetch_one(
        """
        INSERT INTO app.telem_group (satellite_id, name, description)
        VALUES (%s, %s, %s)
        ON CONFLICT (satellite_id, name) DO UPDATE SET description = EXCLUDED.description
        RETURNING id, satellite_id, name, description
        """,
        (payload.satellite_id, payload.name, payload.description),
    )
    for order, channel_id in enumerate(payload.channel_ids):
        await execute(
            "INSERT INTO app.group_member (group_id, channel_id, display_order) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (row["id"], channel_id, order),
        )
    return Group(**row, members=await _members(row["id"]))


@router.get("/{group_id}", response_model=Group)
async def get_group(group_id: uuid.UUID):
    row = await fetch_one(
        "SELECT id, satellite_id, name, description FROM app.telem_group WHERE id = %s",
        (group_id,),
    )
    if not row:
        raise HTTPException(404, "group not found")
    return Group(**row, members=await _members(group_id))


@router.post("/{group_id}/members", status_code=204)
async def add_member(group_id: uuid.UUID, channel_id: uuid.UUID, axis: int = 0):
    await execute(
        "INSERT INTO app.group_member (group_id, channel_id, axis) VALUES (%s, %s, %s) "
        "ON CONFLICT (group_id, channel_id) DO UPDATE SET axis = EXCLUDED.axis",
        (group_id, channel_id, axis),
    )


@router.delete("/{group_id}/members/{channel_id}", status_code=204)
async def remove_member(group_id: uuid.UUID, channel_id: uuid.UUID):
    await execute(
        "DELETE FROM app.group_member WHERE group_id = %s AND channel_id = %s",
        (group_id, channel_id),
    )


@router.delete("/{group_id}", status_code=204)
async def delete_group(group_id: uuid.UUID):
    await execute("DELETE FROM app.telem_group WHERE id = %s", (group_id,))
'''

FILES["api/routers/labels.py"] = '''"""Labels: regions drawn by a human, or proposed by a model and reviewed.

This is the feedback loop. Confirmed labels are what a retrain manifest
consumes; rejected ones feed precision. Model output never becomes training
data without a human touching it.
"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException, Query
from psycopg.types.range import TimestamptzRange

from ..db import execute, fetch_all, fetch_one
from ..schemas import Label, LabelCreate, TaxonomyItem

router = APIRouter(prefix="/labels", tags=["labels"])

SELECT_SQL = """
SELECT l.id, l.group_id, l.channel_id,
       lower(l.time_range) AS start, upper(l.time_range) AS "end",
       l.label_class::text, t.code AS taxonomy_code, t.name AS taxonomy_name,
       t.color, l.review_status::text, l.note, l.created_at
FROM labels.label l
LEFT JOIN labels.taxonomy t ON t.id = l.taxonomy_id
"""


@router.get("/taxonomy", response_model=list[TaxonomyItem])
async def list_taxonomy():
    return await fetch_all(
        "SELECT id, label_class::text, code, name, description, color "
        "FROM labels.taxonomy WHERE active ORDER BY label_class, name"
    )


@router.get("", response_model=list[Label])
async def list_labels(
    group_id: uuid.UUID,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    review_status: str | None = Query(None),
):
    where = ["l.group_id = %s"]
    params: list = [group_id]
    if start and end:
        where.append("l.time_range && tstzrange(%s, %s)")
        params.extend([start, end])
    if review_status:
        where.append("l.review_status = %s")
        params.append(review_status)
    return await fetch_all(
        SELECT_SQL + " WHERE " + " AND ".join(where) + " ORDER BY lower(l.time_range)",
        tuple(params),
    )


@router.post("", response_model=Label, status_code=201)
async def create_label(payload: LabelCreate):
    if payload.end <= payload.start:
        raise HTTPException(400, "end must be after start")

    taxonomy_id = None
    if payload.taxonomy_code:
        row = await fetch_one(
            "SELECT id FROM labels.taxonomy WHERE code = %s", (payload.taxonomy_code,)
        )
        if not row:
            raise HTTPException(400, f"unknown taxonomy code {payload.taxonomy_code!r}")
        taxonomy_id = row["id"]

    created = await fetch_one(
        """
        INSERT INTO labels.label
            (group_id, channel_id, time_range, label_class, taxonomy_id,
             review_status, note)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            payload.group_id,
            payload.channel_id,
            TimestamptzRange(payload.start, payload.end, "[)"),
            payload.label_class,
            taxonomy_id,
            payload.review_status,
            payload.note,
        ),
    )
    rows = await fetch_all(SELECT_SQL + " WHERE l.id = %s", (created["id"],))
    return rows[0]


@router.patch("/{label_id}/status", response_model=Label)
async def set_status(label_id: uuid.UUID, review_status: str):
    if review_status not in {"proposed", "accepted", "rejected", "missed"}:
        raise HTTPException(400, "invalid review_status")
    await execute(
        "UPDATE labels.label SET review_status = %s, updated_at = now() WHERE id = %s",
        (review_status, label_id),
    )
    rows = await fetch_all(SELECT_SQL + " WHERE l.id = %s", (label_id,))
    if not rows:
        raise HTTPException(404, "label not found")
    return rows[0]


@router.delete("/{label_id}", status_code=204)
async def delete_label(label_id: uuid.UUID):
    await execute("DELETE FROM labels.label WHERE id = %s", (label_id,))
'''

FILES["api/routers/registry.py"] = '''"""Model registry - deliberately thin.

Tables exist (see migrations/012_ml.sql) so the retrain and signoff flow can be
built without another migration. These endpoints cover listing and promotion;
training orchestration and inference are future work.

The promotion endpoint is the human gate: scheduled retrains may produce
candidates, but only a person moves one to `promoted`.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from ..db import execute, fetch_all, fetch_one

router = APIRouter(prefix="/registry", tags=["registry"])


@router.get("/models")
async def list_models(group_id: uuid.UUID | None = None):
    if group_id:
        return await fetch_all(
            """
            SELECT m.id, m.name, m.algorithm, b.is_default
            FROM ml.model m
            JOIN ml.model_group_binding b ON b.model_id = m.id
            WHERE b.group_id = %s
            ORDER BY m.name
            """,
            (group_id,),
        )
    return await fetch_all("SELECT id, name, algorithm FROM ml.model ORDER BY name")


@router.get("/models/{model_id}/versions")
async def list_versions(model_id: uuid.UUID):
    return await fetch_all(
        """
        SELECT v.id, v.version, v.status::text, v.eval_metrics,
               v.created_at, v.promoted_at, man.content_hash
        FROM ml.model_version v
        LEFT JOIN ml.manifest man ON man.id = v.manifest_id
        WHERE v.model_id = %s
        ORDER BY v.version DESC
        """,
        (model_id,),
    )


@router.post("/versions/{version_id}/promote")
async def promote(version_id: uuid.UUID):
    """The human gate. Retires whichever version was previously promoted."""
    row = await fetch_one(
        "SELECT model_id FROM ml.model_version WHERE id = %s", (version_id,)
    )
    if not row:
        raise HTTPException(404, "version not found")
    await execute(
        "UPDATE ml.model_version SET status = 'retired' "
        "WHERE model_id = %s AND status = 'promoted'",
        (row["model_id"],),
    )
    await execute(
        "UPDATE ml.model_version SET status = 'promoted', promoted_at = now() "
        "WHERE id = %s",
        (version_id,),
    )
    return {"id": str(version_id), "status": "promoted"}
'''

FILES["api/main.py"] = '''"""FastAPI application entrypoint."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import cors_origins
from .db import close_pool, fetch_one, open_pool
from .routers import catalog, groups, labels, registry, timeseries


@asynccontextmanager
async def lifespan(app: FastAPI):
    await open_pool()
    yield
    await close_pool()


app = FastAPI(
    title="telemetry-platform API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(catalog.router)
app.include_router(timeseries.router)
app.include_router(groups.router)
app.include_router(labels.router)
app.include_router(registry.router)


@app.get("/health")
async def health():
    row = await fetch_one("SELECT 1 AS ok")
    return {"status": "ok", "db": bool(row and row["ok"] == 1)}
'''

FILES["api/migrate.py"] = '''"""Apply this repo's migrations (010+) via psql.

telemetry-db's migrations must already be applied: 010_app.sql references
catalog.satellite and catalog.channel.
"""
import pathlib
import subprocess
import sys

from .config import database_url

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parents[1] / "migrations"


def main() -> None:
    dsn = database_url()
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print(f"no .sql files in {MIGRATIONS_DIR}")
        return
    for path in files:
        print(f"apply {path.name}")
        result = subprocess.run(
            ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
            raise SystemExit(f"failed: {path.name}")
    print("done")


if __name__ == "__main__":
    main()
'''

FILES["docker/api/Dockerfile"] = '''FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

RUN apt-get update \\
 && apt-get install -y --no-install-recommends postgresql-client \\
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT=/usr/local \\
    UV_COMPILE_BYTECODE=1 \\
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY api ./api
COPY migrations ./migrations

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
'''

# ---------------------------------------------------------------------------
# Web
# ---------------------------------------------------------------------------

FILES["web/package.json"] = '''{
  "name": "telemetry-platform-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "echarts": "^5.5.1",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.3",
    "typescript": "^5.6.3",
    "vite": "^5.4.10"
  }
}
'''

FILES["web/vite.config.ts"] = '''import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\\/api/, ""),
      },
    },
  },
});
'''

FILES["web/tsconfig.json"] = '''{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "resolveJsonModule": true
  },
  "include": ["src"]
}
'''

FILES["web/index.html"] = '''<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Telemetry Platform</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
'''

FILES["web/src/main.tsx"] = '''import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
'''

FILES["web/src/styles.css"] = ''':root {
  --bg: #14140f;
  --panel: #1c1c17;
  --border: #2e2e28;
  --text: #e8e6dc;
  --muted: #9c9a92;
  --accent: #c96442;
  color-scheme: dark;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, sans-serif;
}

button, select, input {
  background: var(--panel);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 5px 10px;
  font: inherit;
}

button { cursor: pointer; }
button:hover { border-color: var(--accent); }

.layout { display: grid; grid-template-columns: 260px 1fr; height: 100vh; }
.sidebar { border-right: 1px solid var(--border); overflow-y: auto; padding: 12px; }
.main { display: flex; flex-direction: column; overflow: hidden; }
.toolbar {
  display: flex; gap: 8px; align-items: center;
  padding: 10px 14px; border-bottom: 1px solid var(--border); flex-wrap: wrap;
}
.chart-wrap { flex: 1; min-height: 0; padding: 10px 14px; }
.muted { color: var(--muted); }
.tree-item { padding: 3px 6px; border-radius: 5px; cursor: pointer; }
.tree-item:hover { background: var(--panel); }
.tree-item.active { background: var(--panel); color: var(--accent); }
.chip {
  display: inline-flex; gap: 6px; align-items: center;
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 999px; padding: 2px 10px; font-size: 12px;
}
'''

FILES["web/src/api/client.ts"] = '''// Thin typed client. Vite proxies /api -> http://localhost:8000

export interface Satellite {
  id: string;
  designator: string;
  bus_design?: string | null;
  launch_date?: string | null;
}

export interface Subsystem {
  id: string;
  satellite_id: string;
  code: string;
  name?: string | null;
  channel_count?: number | null;
}

export interface Channel {
  id: string;
  subsystem_id: string;
  subsystem_code?: string | null;
  mnemonic: string;
  display_name?: string | null;
  units?: string | null;
}

export interface Point {
  t: string;
  v: number | null;
  lo: number | null;
  hi: number | null;
  p05: number | null;
  p95: number | null;
}

export interface Series {
  channel_id: string;
  mnemonic: string;
  units?: string | null;
  tier: string;
  bucket_seconds: number | null;
  points: Point[];
}

export interface TimeseriesResponse {
  start: string;
  end: string;
  tier: string;
  series: Series[];
}

export interface Label {
  id: string;
  group_id: string;
  start: string;
  end: string;
  label_class: string;
  taxonomy_code?: string | null;
  taxonomy_name?: string | null;
  color?: string | null;
  review_status: string;
  note?: string | null;
}

export interface TaxonomyItem {
  id: string;
  label_class: string;
  code: string;
  name: string;
  color?: string | null;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${path}`);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${path}`);
  return res.status === 204 ? (undefined as T) : res.json();
}

export const api = {
  satellites: () => get<Satellite[]>("/catalog/satellites"),

  subsystems: (satelliteId: string) =>
    get<Subsystem[]>(`/catalog/satellites/${satelliteId}/subsystems`),

  channels: (params: { q?: string; subsystem_id?: string; satellite_id?: string }) => {
    const qs = new URLSearchParams();
    if (params.q) qs.set("q", params.q);
    if (params.subsystem_id) qs.set("subsystem_id", params.subsystem_id);
    if (params.satellite_id) qs.set("satellite_id", params.satellite_id);
    return get<Channel[]>(`/catalog/channels?${qs}`);
  },

  extent: (channelId: string) =>
    get<{ first: string | null; last: string | null; n: number }>(
      `/timeseries/extent?channel_id=${channelId}`
    ),

  timeseries: (channelIds: string[], start: string, end: string, tier?: string) => {
    const qs = new URLSearchParams();
    channelIds.forEach((id) => qs.append("channel_ids", id));
    qs.set("start", start);
    qs.set("end", end);
    if (tier) qs.set("tier", tier);
    return get<TimeseriesResponse>(`/timeseries?${qs}`);
  },

  taxonomy: () => get<TaxonomyItem[]>("/labels/taxonomy"),

  labels: (groupId: string, start?: string, end?: string) => {
    const qs = new URLSearchParams({ group_id: groupId });
    if (start) qs.set("start", start);
    if (end) qs.set("end", end);
    return get<Label[]>(`/labels?${qs}`);
  },

  createLabel: (payload: {
    group_id: string;
    start: string;
    end: string;
    label_class: string;
    taxonomy_code?: string;
    note?: string;
  }) => post<Label>("/labels", payload),
};
'''

FILES["web/src/features/catalog/CatalogTree.tsx"] = '''import { useEffect, useState } from "react";
import { api, type Satellite, type Subsystem } from "../../api/client";

// The tree stops at subsystem on purpose. With thousands of channels per
// satellite the fourth level is a search problem, handled by ChannelFinder.
export function CatalogTree({
  onSelectSubsystem,
  selectedId,
}: {
  onSelectSubsystem: (s: Subsystem, satellite: Satellite) => void;
  selectedId?: string;
}) {
  const [satellites, setSatellites] = useState<Satellite[]>([]);
  const [expanded, setExpanded] = useState<Record<string, Subsystem[]>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.satellites().then(setSatellites).catch((e) => setError(String(e)));
  }, []);

  async function toggle(sat: Satellite) {
    if (expanded[sat.id]) {
      const next = { ...expanded };
      delete next[sat.id];
      setExpanded(next);
      return;
    }
    const subs = await api.subsystems(sat.id);
    setExpanded({ ...expanded, [sat.id]: subs });
  }

  if (error) return <div className="muted">catalog unavailable: {error}</div>;

  return (
    <div>
      <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
        Satellites
      </div>
      {satellites.map((sat) => (
        <div key={sat.id}>
          <div className="tree-item" onClick={() => toggle(sat)}>
            {expanded[sat.id] ? "\\u25be" : "\\u25b8"} {sat.designator}
          </div>
          {expanded[sat.id]?.map((sub) => (
            <div
              key={sub.id}
              className={`tree-item ${selectedId === sub.id ? "active" : ""}`}
              style={{ paddingLeft: 20 }}
              onClick={() => onSelectSubsystem(sub, sat)}
            >
              {sub.code}{" "}
              <span className="muted" style={{ fontSize: 12 }}>
                {sub.channel_count}
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
'''

FILES["web/src/features/catalog/ChannelFinder.tsx"] = '''import { useEffect, useState } from "react";
import { api, type Channel } from "../../api/client";

// Finding one channel among thousands is typing, not scrolling.
export function ChannelFinder({
  subsystemId,
  selected,
  onToggle,
}: {
  subsystemId?: string;
  selected: Channel[];
  onToggle: (c: Channel) => void;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Channel[]>([]);

  useEffect(() => {
    const handle = setTimeout(() => {
      api
        .channels({ q: q || undefined, subsystem_id: subsystemId })
        .then(setResults)
        .catch(() => setResults([]));
    }, 200);
    return () => clearTimeout(handle);
  }, [q, subsystemId]);

  const selectedIds = new Set(selected.map((c) => c.id));

  return (
    <div style={{ marginTop: 14 }}>
      <input
        placeholder="search channels..."
        value={q}
        onChange={(e) => setQ(e.target.value)}
        style={{ width: "100%" }}
      />
      <div style={{ marginTop: 8 }}>
        {results.map((c) => (
          <div
            key={c.id}
            className={`tree-item ${selectedIds.has(c.id) ? "active" : ""}`}
            onClick={() => onToggle(c)}
            title={c.display_name ?? c.mnemonic}
          >
            {selectedIds.has(c.id) ? "\\u2713 " : ""}
            {c.mnemonic}
          </div>
        ))}
        {results.length === 0 && (
          <div className="muted" style={{ fontSize: 12 }}>
            no matches
          </div>
        )}
      </div>
    </div>
  );
}
'''

FILES["web/src/features/chart/TelemetryChart.tsx"] = '''import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { Label, Series } from "../../api/client";

// ECharts is enough because the API caps points per channel. Aggregate tiers
// carry min/q05/q95/max, drawn as a translucent envelope behind the mean.
export function TelemetryChart({
  series,
  labels,
  onBrush,
}: {
  series: Series[];
  labels: Label[];
  onBrush?: (start: Date, end: Date) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, "dark", { renderer: "canvas" });
    chartRef.current = chart;
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    const dataSeries: echarts.SeriesOption[] = [];

    series.forEach((s) => {
      const hasEnvelope = s.points.some((p) => p.lo !== null && p.hi !== null);

      if (hasEnvelope) {
        // Band drawn as a floor plus a stacked delta with area fill.
        dataSeries.push({
          name: `${s.mnemonic} lo`,
          type: "line",
          data: s.points.map((p) => [p.t, p.lo]),
          lineStyle: { opacity: 0 },
          stack: `band-${s.channel_id}`,
          symbol: "none",
          silent: true,
          tooltip: { show: false },
        });
        dataSeries.push({
          name: `${s.mnemonic} band`,
          type: "line",
          data: s.points.map((p) => [
            p.t,
            p.hi !== null && p.lo !== null ? p.hi - p.lo : null,
          ]),
          lineStyle: { opacity: 0 },
          areaStyle: { opacity: 0.15 },
          stack: `band-${s.channel_id}`,
          symbol: "none",
          silent: true,
          tooltip: { show: false },
        });
      }

      dataSeries.push({
        name: s.mnemonic,
        type: "line",
        data: s.points.map((p) => [p.t, p.v]),
        symbol: "none",
        sampling: "lttb",
        lineStyle: { width: 1.4 },
        connectNulls: false, // gaps are real; do not bridge them
        markArea: labels.length
          ? {
              silent: true,
              itemStyle: { opacity: 0.18 },
              data: labels.map((l) => [
                {
                  xAxis: l.start,
                  itemStyle: { color: l.color ?? "#993C1D" },
                  name: l.taxonomy_name ?? l.label_class,
                },
                { xAxis: l.end },
              ]),
            }
          : undefined,
      });
    });

    chart.setOption(
      {
        backgroundColor: "transparent",
        animation: false,
        grid: { left: 60, right: 24, top: 30, bottom: 60 },
        legend: {
          data: series.map((s) => s.mnemonic),
          textStyle: { color: "#9c9a92" },
          top: 0,
        },
        tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
        xAxis: { type: "time", axisLine: { lineStyle: { color: "#2e2e28" } } },
        yAxis: {
          type: "value",
          scale: true,
          splitLine: { lineStyle: { color: "#2e2e28" } },
        },
        dataZoom: [
          { type: "inside", filterMode: "none" },
          { type: "slider", height: 22, bottom: 12 },
        ],
        brush: {
          toolbox: ["lineX", "clear"],
          xAxisIndex: 0,
          throttleType: "debounce",
          throttleDelay: 300,
        },
        series: dataSeries,
      },
      { replaceMerge: ["series"] }
    );

    const handler = (params: any) => {
      const area = params?.areas?.[0];
      if (!area || !onBrush) return;
      const [a, b] = area.coordRange ?? [];
      if (a != null && b != null) onBrush(new Date(a), new Date(b));
    };
    chart.off("brushEnd");
    chart.on("brushEnd", handler);
  }, [series, labels, onBrush]);

  return <div ref={ref} style={{ width: "100%", height: "100%" }} />;
}
'''

FILES["web/src/features/labeling/LabelPanel.tsx"] = '''import { useEffect, useState } from "react";
import { api, type TaxonomyItem } from "../../api/client";

// Anomaly vs off-nominal is a distinction satellite operators draw, so it is
// native to the UI rather than a note field.
export function LabelPanel({
  selection,
  groupId,
  onSaved,
}: {
  selection: { start: Date; end: Date } | null;
  groupId: string | null;
  onSaved: () => void;
}) {
  const [taxonomy, setTaxonomy] = useState<TaxonomyItem[]>([]);
  const [code, setCode] = useState<string>("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.taxonomy().then((items) => {
      setTaxonomy(items);
      if (items.length) setCode(items[0].code);
    });
  }, []);

  if (!selection) {
    return (
      <span className="muted">
        drag on the chart to select a window
      </span>
    );
  }
  if (!groupId) {
    return <span className="muted">create a group before labeling</span>;
  }

  const chosen = taxonomy.find((t) => t.code === code);

  async function save() {
    if (!chosen || !selection || !groupId) return;
    setBusy(true);
    try {
      await api.createLabel({
        group_id: groupId,
        start: selection.start.toISOString(),
        end: selection.end.toISOString(),
        label_class: chosen.label_class,
        taxonomy_code: chosen.code,
        note: note || undefined,
      });
      setNote("");
      onSaved();
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <span className="chip">
        {selection.start.toISOString().slice(0, 16)} &rarr;{" "}
        {selection.end.toISOString().slice(0, 16)}
      </span>
      <select value={code} onChange={(e) => setCode(e.target.value)}>
        <optgroup label="Anomaly">
          {taxonomy
            .filter((t) => t.label_class === "anomaly")
            .map((t) => (
              <option key={t.code} value={t.code}>
                {t.name}
              </option>
            ))}
        </optgroup>
        <optgroup label="Off-nominal">
          {taxonomy
            .filter((t) => t.label_class === "off_nominal")
            .map((t) => (
              <option key={t.code} value={t.code}>
                {t.name}
              </option>
            ))}
        </optgroup>
      </select>
      <input
        placeholder="note (optional)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        style={{ width: 180 }}
      />
      <button onClick={save} disabled={busy}>
        {busy ? "saving..." : "Save label"}
      </button>
    </>
  );
}
'''

FILES["web/src/App.tsx"] = '''import { useCallback, useEffect, useState } from "react";
import { CatalogTree } from "./features/catalog/CatalogTree";
import { ChannelFinder } from "./features/catalog/ChannelFinder";
import { TelemetryChart } from "./features/chart/TelemetryChart";
import { LabelPanel } from "./features/labeling/LabelPanel";
import { api, type Channel, type Label, type Series } from "./api/client";

export default function App() {
  const [subsystemId, setSubsystemId] = useState<string | undefined>();
  const [selected, setSelected] = useState<Channel[]>([]);
  const [series, setSeries] = useState<Series[]>([]);
  const [labels, setLabels] = useState<Label[]>([]);
  const [groupId, setGroupId] = useState<string | null>(null);
  const [range, setRange] = useState<{ start: string; end: string } | null>(null);
  const [selection, setSelection] = useState<{ start: Date; end: Date } | null>(null);
  const [tier, setTier] = useState<string>("");

  // Frame the initial view from the first selected channel's extent.
  useEffect(() => {
    if (!selected.length) {
      setSeries([]);
      setRange(null);
      return;
    }
    api.extent(selected[0].id).then((e) => {
      if (e.first && e.last) setRange({ start: e.first, end: e.last });
    });
  }, [selected]);

  useEffect(() => {
    if (!selected.length || !range) return;
    api
      .timeseries(selected.map((c) => c.id), range.start, range.end)
      .then((res) => {
        setSeries(res.series);
        setTier(res.tier);
      })
      .catch(() => setSeries([]));
  }, [selected, range]);

  const reloadLabels = useCallback(() => {
    if (!groupId || !range) return;
    api.labels(groupId, range.start, range.end).then(setLabels).catch(() => setLabels([]));
  }, [groupId, range]);

  useEffect(reloadLabels, [reloadLabels]);

  function toggleChannel(c: Channel) {
    setSelected((prev) =>
      prev.some((x) => x.id === c.id)
        ? prev.filter((x) => x.id !== c.id)
        : [...prev, c]
    );
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <CatalogTree
          selectedId={subsystemId}
          onSelectSubsystem={(sub) => setSubsystemId(sub.id)}
        />
        <ChannelFinder
          subsystemId={subsystemId}
          selected={selected}
          onToggle={toggleChannel}
        />
      </aside>

      <main className="main">
        <div className="toolbar">
          {selected.length === 0 && (
            <span className="muted">pick channels from the finder</span>
          )}
          {selected.map((c) => (
            <span key={c.id} className="chip">
              {c.mnemonic}
              <button
                style={{ padding: "0 4px", border: "none", background: "none" }}
                onClick={() => toggleChannel(c)}
              >
                &times;
              </button>
            </span>
          ))}
          {tier && <span className="muted">tier: {tier}</span>}
        </div>

        <div className="toolbar">
          <LabelPanel
            selection={selection}
            groupId={groupId}
            onSaved={() => {
              setSelection(null);
              reloadLabels();
            }}
          />
        </div>

        <div className="chart-wrap">
          {series.length ? (
            <TelemetryChart
              series={series}
              labels={labels}
              onBrush={(start, end) => setSelection({ start, end })}
            />
          ) : (
            <div className="muted" style={{ padding: 24 }}>
              no data loaded
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
'''

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

FILES["tests/__init__.py"] = '''# tests
'''

FILES["tests/test_tiers.py"] = '''"""Tier selection is the load-bearing performance decision; test it directly."""
import datetime as dt

from api.tiers import pick_tier

MAX = 2000


def window(**kwargs) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime(2010, 1, 1, tzinfo=dt.timezone.utc)
    return start, start + dt.timedelta(**kwargs)


def test_short_window_uses_raw():
    bucket, name = pick_tier(*window(minutes=20), MAX)
    assert (bucket, name) == (None, "raw")


def test_multi_day_window_uses_10min():
    bucket, name = pick_tier(*window(days=7), MAX)
    assert (bucket, name) == (600, "10min")


def test_mission_span_uses_6h():
    bucket, name = pick_tier(*window(days=1600), MAX)
    assert (bucket, name) == (21600, "6h")


def test_never_exceeds_budget_when_possible():
    start, end = window(days=7)
    bucket, _ = pick_tier(start, end, MAX)
    assert (end - start).total_seconds() / (bucket or 1) <= MAX
'''

FILES["tests/test_health.py"] = '''"""Import smoke test - does not require a live database."""


def test_app_exposes_expected_routes():
    from api.main import app

    paths = set(app.openapi()["paths"])
    assert "/health" in paths
    assert any(p.startswith("/timeseries") for p in paths)
    assert any(p.startswith("/labels") for p in paths)
    assert any(p.startswith("/catalog") for p in paths)
    assert any(p.startswith("/groups") for p in paths)
'''

EXECUTABLE: set[str] = set()

_MK = [
    ".DEFAULT_GOAL := help",
    "",
    "help:",
    "\t@grep -E '^[a-zA-Z_-]+:.*?## .*$$' Makefile | sort | \\",
    "\t\tawk 'BEGIN {FS = \":.*?## \"}; {printf \"  %-12s %s\\n\", $$1, $$2}'",
    "",
    "dev: ## Create .venv and sync deps",
    "\tuv sync",
    "",
    "migrate: ## Apply platform migrations (010+) to the database",
    "\tuv run python -m api.migrate",
    "",
    "api: ## Run the API with reload",
    "\tuv run uvicorn api.main:app --reload --port 8000",
    "",
    "web: ## Run the web dev server",
    "\tcd web && npm run dev",
    "",
    "install-web: ## Install web dependencies",
    "\tcd web && npm install",
    "",
    "test: ## Run tests",
    "\tuv run pytest -q",
    "",
    "lint: ## Lint python",
    "\tuv run ruff check .",
    "",
    ".PHONY: help dev migrate api web install-web test lint",
    "",
]
FILES["Makefile"] = "\n".join(_MK)


def write_tree(root: str, force: bool) -> None:
    created = 0
    skipped: list[str] = []
    for rel, content in FILES.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if os.path.exists(path) and not force:
            skipped.append(rel)
            continue
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        if rel in EXECUTABLE:
            st = os.stat(path)
            os.chmod(path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        created += 1

    print(f"{created} file(s) written, {len(skipped)} skipped (already existed).")
    for rel in skipped:
        print(f"  skipped: {rel}")
    if skipped:
        print("  re-run with --force to overwrite these.")


def print_tree(root: str) -> None:
    display = os.path.basename(os.path.abspath(root))
    print(f"{display}/")

    def walk(directory: str, prefix: str) -> None:
        entries = sorted(os.scandir(directory), key=lambda e: (not e.is_dir(), e.name))
        entries = [e for e in entries if e.name not in {"__pycache__", "node_modules"}]
        for index, entry in enumerate(entries):
            last = index == len(entries) - 1
            print(f"{prefix}{'`-- ' if last else '|-- '}{entry.name}"
                  f"{'/' if entry.is_dir() else ''}")
            if entry.is_dir():
                walk(entry.path, prefix + ("    " if last else "|   "))

    walk(root, "")


def main() -> None:
    ap = argparse.ArgumentParser(description="Scaffold the telemetry-platform repo.")
    ap.add_argument("--root", default=".", help="target directory (default: current)")
    ap.add_argument("--force", action="store_true", help="overwrite existing files")
    args = ap.parse_args()
    write_tree(args.root, args.force)
    print()
    print_tree(args.root)
    prefix = "" if args.root == "." else f"cd {args.root} && "
    print(f"\nNext: {prefix}cp .env.example .env && uv sync && make migrate && make api")


if __name__ == "__main__":
    main()