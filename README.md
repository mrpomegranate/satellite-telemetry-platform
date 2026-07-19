# satellite-telemetry-platform

Visualization, labeling and prediction platform for satellite telemetry.

Browse a satellite's channels, plot them at whatever resolution the time window
calls for, draw labels on regions of interest, and (later) run anomaly models
over a selected window and review what they propose.

This is the **application** half of a two-repo system. The **data** half lives in
[`satellite-telemetry-db`](#prerequisite-the-database-repo), which owns the
telemetry itself. Both write to the same Postgres database.

---

## Contents

- [How the two repos fit together](#how-the-two-repos-fit-together)
- [Prerequisites](#prerequisites)
- [Prerequisite: the database repo](#prerequisite-the-database-repo)
- [Setup](#setup)
- [Running it](#running-it)
- [Using the app](#using-the-app)
- [How the chart works](#how-the-chart-works)
- [API reference](#api-reference)
- [Project layout](#project-layout)
- [Troubleshooting](#troubleshooting)
- [Development notes](#development-notes)

---

## How the two repos fit together

One database per **program**. Satellites live inside it as rows, so comparing
two satellites in the same program stays an ordinary SQL join. Each repo owns
its own schemas and migrates only those.

| Repo | Schemas | Owns |
|------|---------|------|
| `satellite-telemetry-db` | `catalog`, `telemetry` | satellites, subsystems, channels, samples |
| `satellite-telemetry-platform` (this) | `app`, `labels`, `ml` | groups, labels, models, manifests |

Foreign keys cross **one way only**: platform → catalog. The database repo does
not know that groups or models exist. Migration numbering makes the order
obvious — `001`–`004` in the db repo, `010`+ here.

```
                 ┌─────────────────────────────────────┐
   browser ──────│  web  (React + Vite + ECharts)      │
                 └──────────────┬──────────────────────┘
                                │  /api  (Vite proxy)
                 ┌──────────────▼──────────────────────┐
                 │  api  (FastAPI)                     │
                 └──────────────┬──────────────────────┘
                                │  psycopg pool
                 ┌──────────────▼──────────────────────┐
                 │  Postgres + TimescaleDB             │
                 │  catalog · telemetry  (db repo)     │
                 │  app · labels · ml    (this repo)   │
                 └─────────────────────────────────────┘
```

---

## Prerequisites

| Tool | Why | Install |
|------|-----|---------|
| [uv](https://docs.astral.sh/uv/) | Python deps and venv | `winget install astral-sh.uv` / `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| [Node.js](https://nodejs.org) 20+ | web dev server | `winget install OpenJS.NodeJS.LTS` |
| [Docker Desktop](https://docker.com) | runs the database | required by the db repo |

Python 3.12 is pinned via `.python-version`; uv provisions it for you.

You do **not** need `make` (a Makefile is provided for convenience, but every
command has a direct equivalent below) or a local `psql` client (migrations run
through psycopg).

---

## Prerequisite: the database repo

The platform reads telemetry the db repo ingests, so bring that up first.

```bash
git clone <url> satellite-telemetry-db
cd satellite-telemetry-db
cp .env.example .env          # Windows: Copy-Item .env.example .env
uv sync
docker compose up -d db
docker compose --profile tools run --rm migrate migrate
```

Then load some telemetry. The GOCE dataset is a good demo set — real ESA flight
data, March 2009 to October 2013:

```bash
# ~4 MB: 12 channels spread across subsystem families, 6-hour tier
uv run scripts/fetch_goce.py -n 12 --spread
docker compose --profile tools run --rm migrate ingest --tier 6h
```

Verify before moving on:

```sql
SELECT sub.code, c.mnemonic, count(*) AS buckets
FROM telemetry.sample_stats ss
JOIN catalog.channel c ON c.id = ss.channel_id
JOIN catalog.subsystem sub ON sub.id = c.subsystem_id
GROUP BY sub.code, c.mnemonic ORDER BY sub.code;
```

You should see one row per channel at roughly 6,656 buckets each.

---

## Setup

```bash
git clone <url> satellite-telemetry-platform
cd satellite-telemetry-platform
cp .env.example .env          # Windows: Copy-Item .env.example .env
```

Edit `.env` so `DATABASE_URL` points at the same database the db repo created.
Use `localhost` — you are connecting from the host, not from inside Docker:

```ini
DATABASE_URL=postgresql://telemetry:telemetry@localhost:5432/esa
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=http://localhost:5173
MAX_POINTS=2000
```

Install dependencies:

```bash
uv sync                  # Python: FastAPI, uvicorn, psycopg
cd web && npm install    # web: React, Vite, TypeScript, ECharts
cd ..
```

Apply this repo's migrations (`010`–`012`). The db repo's must already be
applied, since `010_app.sql` references `catalog.satellite`:

```bash
uv run python -m api.migrate
```

Expected output:

```
apply 010_app.sql
apply 011_labels.sql
apply 012_ml.sql
done
```

---

## Running it

Two processes, two terminals.

**Terminal 1 — API**

```bash
uv run uvicorn api.main:app --reload --port 8000
```

Check <http://127.0.0.1:8000/health> — it should return
`{"status":"ok","db":true}`. Interactive docs at
<http://127.0.0.1:8000/docs>.

**Terminal 2 — web**

```bash
cd web
npm run dev
```

Open <http://localhost:5173>.

With `make` installed, `make api` and `make web` do the same thing.

---

## Using the app

**Find channels.** The sidebar tree goes satellite → subsystem and deliberately
stops there. A satellite can carry thousands of channels, so the fourth level is
a search problem, not a tree problem — click a subsystem to scope the finder,
then type to filter. Click a result to add it to the chart; click again to
remove it.

**Read the chart.** The caption under the plot always states what you are
looking at: what the line is, what the shading is, how much time each point
covers, and how many points are drawn. Hover any point for the full breakdown —
bucket start and end, max / q95 / mean / q05 / min in the channel's units, and
how many raw readings were aggregated into it.

**Toolbar controls.**

| Control | Does |
|---------|------|
| `one chart` / `split` | overlay all channels, or give each its own pane and Y scale |
| `5-95%` / `min/max` / `off` | which envelope to shade |
| `mean line` | show or hide the mean line, leaving the envelope alone |
| `L` / `R` on a chip | move that channel to the other Y axis (overlay mode) |
| sun / moon | light or dark theme, remembered between sessions |

Use **split** when channels differ by orders of magnitude — one flat carpet plus
one sawtooth on a shared axis tells you nothing. Use **overlay** with `L`/`R`
when you are comparing two channels and want them on the same time cursor.

**Label a region.** Drag across the chart to select a window, pick a type, and
save. Labels appear as shaded regions on every chart showing that group.

> **Note:** labeling needs a telemetry group, and the group picker is not built
> yet. Until it is, create one through the API — `POST /groups` in
> <http://127.0.0.1:8000/docs> — and the label panel will unlock.

---

## How the chart works

The browser never receives more than `MAX_POINTS` (default 2,000) per channel.
`/timeseries` picks the finest tier that fits the requested window and reads the
matching table:

| Window | Tier | Source |
|--------|------|--------|
| months – years | 6 h buckets | `telemetry.sample_stats` (`bucket_seconds = 21600`) |
| days – weeks | 10 min buckets | `telemetry.sample_stats` (`bucket_seconds = 600`) |
| minutes – hours | raw samples | `telemetry.sample` |

This is why the UI stays responsive over 4.5 years of telemetry without any
client-side heroics: the point count is capped server-side regardless of how
much data exists.

Aggregate tiers carry `min`, `q05`, `mean`, `q95`, `max` and a sample count, so
each point is drawn as a **vertical slice** — a shaded band with the mean marked
inside it — rather than a bare dot. Thousands of slices side by side read as a
continuous ribbon.

Two behaviours worth knowing:

- **Gaps stay gaps.** `connectNulls` is off, so missing telemetry is not bridged
  by a straight line. In satellite data a gap is information.
- **A skewed band is signal.** The mean sits inside the envelope but rarely at
  its centre; when it sits well off-centre, the distribution within that bucket
  is skewed.

If a tier has no data (you ingested only `6h` but zoomed to an hour), the chart
comes back empty. That is correct, not a bug — ingest the finer tier to fill it.

---

## API reference

Full interactive docs at `/docs`. Summary:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | liveness plus a database round trip |
| GET | `/catalog/satellites` | list satellites |
| GET | `/catalog/satellites/{id}/subsystems` | subsystems with channel counts |
| GET | `/catalog/channels` | search by `q`, `subsystem_id`, `satellite_id` |
| GET | `/timeseries` | windowed read with automatic tier selection |
| GET | `/timeseries/extent` | first and last bucket for a channel |
| GET/POST | `/groups` | list and create telemetry groups |
| GET/DELETE | `/groups/{id}` | fetch or delete a group |
| POST/DELETE | `/groups/{id}/members` | add or remove channels |
| GET | `/labels/taxonomy` | the controlled label vocabulary |
| GET/POST | `/labels` | list and create labels |
| PATCH | `/labels/{id}/status` | accept, reject, or mark missed |
| GET | `/registry/models` | registered models, optionally by group |
| POST | `/registry/versions/{id}/promote` | the human gate: promote a candidate |

### Labels

Labels carry a two-class distinction that satellite operators draw:

- **`off_nominal`** — a known, explainable departure (limit violation, expected
  manoeuvre, data gap)
- **`anomaly`** — an unexplained deviation that needs investigation

Types come from `labels.taxonomy`, a seeded table rather than free text, so the
vocabulary stays reportable. Review status (`proposed` / `accepted` /
`rejected` / `missed`) is what turns labels into precision and recall figures
once models are producing proposals.

---

## Project layout

```
satellite-telemetry-platform/
├── api/
│   ├── main.py              FastAPI app and router wiring
│   ├── config.py            environment configuration
│   ├── db.py                async connection pool
│   ├── schemas.py           pydantic request/response models
│   ├── tiers.py             resolution selection (unit tested)
│   ├── migrate.py           applies migrations via psycopg
│   └── routers/
│       ├── catalog.py       satellites, subsystems, channel search
│       ├── timeseries.py    windowed reads, tier selection
│       ├── groups.py        telemetry groups
│       ├── labels.py        labels and taxonomy
│       └── registry.py      model registry (thin, scaffolded)
├── migrations/
│   ├── 010_app.sql          app schema: telem_group, group_member
│   ├── 011_labels.sql       labels schema: taxonomy, label
│   └── 012_ml.sql           ml schema: manifest, model, version, schedule
├── web/
│   └── src/
│       ├── App.tsx          layout and toolbar state
│       ├── theme.ts         light/dark, persisted
│       ├── styles.css       all theming variables
│       ├── api/client.ts    typed API client
│       └── features/
│           ├── catalog/     CatalogTree, ChannelFinder
│           ├── chart/       TelemetryChart, ChartPanes
│           └── labeling/    LabelPanel
├── docker/api/Dockerfile
└── tests/
```

The `ml` schema is deliberately ahead of the code that uses it. `manifest`,
`model_version`, `model_group_binding`, `schedule` and `prediction` all exist so
the training and signoff flow can be built without another migration.

---

## Troubleshooting

**`make` is not recognised (Windows)**
Not required. Use the direct commands:

| Instead of | Run |
|-----------|-----|
| `make migrate` | `uv run python -m api.migrate` |
| `make api` | `uv run uvicorn api.main:app --reload --port 8000` |
| `make web` | `cd web && npm run dev` |
| `make test` | `uv run pytest -q` |

**`node` / `npm` not recognised after installing Node**
Your terminal cached the old `PATH`. Restart the terminal — and in VS Code,
restart the editor itself, since integrated terminals inherit VS Code's
environment.

**`vite http proxy error: ECONNREFUSED`**
The API is not running, or Node resolved `localhost` to IPv6 while uvicorn is
bound to IPv4. `web/vite.config.ts` targets `http://127.0.0.1:8000` for this
reason; make sure the API is up.

**`database "..." does not exist`**
`POSTGRES_DB` only takes effect when the Docker volume is first created. To
rename, recreate it in the db repo (this destroys data):

```bash
docker compose down -v && docker compose up -d db
docker compose --profile tools run --rm migrate migrate
```

**`.env` edits appear ignored**
Confirm what Compose actually resolved, and check the file is saved:

```bash
docker compose config | grep POSTGRES_DB
```

**`data type uuid has no default operator class for access method "gist"`**
`011_labels.sql` creates the `btree_gist` extension for this. If your role
cannot create extensions, replace the combined GiST index with two plain
indexes on `time_range` and `group_id`.

**`relation "telemetry.sample_stats" does not exist`**
The db repo's migration `004` has not been applied. Run its `migrate` again.

**Chart is empty after zooming in**
You are on a tier with no ingested data. Only the `6h` tier is loaded by
default; fetch and ingest `10min` or `raw` for the channels you care about.

**Y axis says "no units recorded"**
`catalog.channel.units` is NULL — the GOCE parquet files carry no unit
metadata. Populate it with an `UPDATE`, or extend the db repo's catalog loader
if you find a metadata source.

---

## Development notes

```bash
uv run pytest -q      # tests (tier selection, route surface)
uv run ruff check .   # lint
cd web && npm run build   # type-check and production build
```

**Adding a migration.** Number it `013`+, keep it idempotent
(`CREATE ... IF NOT EXISTS`, `DO $$ ... EXCEPTION WHEN duplicate_object $$`), and
re-run `uv run python -m api.migrate`. The runner sends each file as one
statement, so Postgres wraps it in an implicit transaction — a failure rolls the
whole file back.

**Reserved words.** `end` and `window` are reserved in Postgres. The label query
quotes `"end"`; the prediction column is `window_range`. Watch for this when
adding columns.

**Air-gapped deployment.** Both toolchains need vendoring:

```bash
uv export --format requirements-txt --no-dev > requirements.lock
uv pip download -r requirements.lock -d vendor/
cd web && npm ci --prefer-offline    # mirror the npm cache alongside
```

Pin image digests and the uv version in `docker/api/Dockerfile` before any
accredited deployment.

**Not built yet.** Group picker and save-as-group, model training and inference,
scheduled retraining, the candidate signoff screen, and graph-based relationship
discovery. The schema supports all of them.
