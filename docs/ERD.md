# Entity relationship diagrams

One Postgres database per **program**. Five schemas, three owners.

| Schema | Owned by | Migrations |
|--------|----------|-----------|
| `catalog`, `telemetry` | `satellite-telemetry-db` | 001–004 |
| `app`, `labels`, `ml` | `satellite-telemetry-platform` | 010+ |
| `public` | MLflow (auto-created) | — |

`satellite-telemetry-mlflow` migrates nothing. It reads `catalog` /
`telemetry` / `labels` and writes rows into `ml.*`.

Foreign keys cross **one way only**: platform → catalog.

---

## Status

| State | Tables |
|-------|--------|
| **Built** (001–012) | satellite, subsystem, channel, sample, sample_stats, telem_group, group_member, taxonomy, label, manifest, model, model_version, model_group_binding, schedule, prediction |
| **Migration 013** | platform_user, label_channel, golden_label view; label gains scope/tier/source/origin_group_id/promoted_by/external_id; taxonomy gains allowed_classes/parent_code/approved |
| **Migration 014 (next)** | pipeline, pipeline_run, node_output, forecast, ruleset, detection_run, llm_call; model gains task; model_version gains threshold |

---

## Data and labelling

```mermaid
erDiagram
  SATELLITE ||--o{ SUBSYSTEM : has
  SUBSYSTEM ||--o{ CHANNEL : has
  CHANNEL ||--o{ SAMPLE : records
  CHANNEL ||--o{ SAMPLE_STATS : aggregates
  CHANNEL ||--o{ GROUP_MEMBER : in
  TELEM_GROUP ||--o{ GROUP_MEMBER : contains
  TELEM_GROUP ||--o{ LABEL : drawn_in
  LABEL ||--o{ LABEL_CHANNEL : implicates
  CHANNEL ||--o{ LABEL_CHANNEL : implicated_by
  TAXONOMY ||--o{ LABEL : types
  PLATFORM_USER ||--o{ LABEL : authors
  PLATFORM_USER ||--o{ TAXONOMY : proposes

  SATELLITE {
    uuid id PK
    string designator
    date launch_date
  }
  SUBSYSTEM {
    uuid id PK
    uuid satellite_id FK
    string code
    string category
  }
  CHANNEL {
    uuid id PK
    uuid subsystem_id FK
    string mnemonic
    string units
    jsonb search_tags
  }
  SAMPLE {
    uuid channel_id FK
    timestamptz ts PK
    double value
  }
  SAMPLE_STATS {
    uuid channel_id FK
    timestamptz bucket PK
    int bucket_seconds PK
    double value_mean
    double value_q05
    double value_q95
    bigint value_count
  }
  TELEM_GROUP {
    uuid id PK
    uuid satellite_id FK
    string name
    bool shared
  }
  GROUP_MEMBER {
    uuid group_id FK
    uuid channel_id FK
    smallint display_order
    smallint axis
  }
  TAXONOMY {
    uuid id PK
    string code
    array allowed_classes
    string parent_code
    bool approved
  }
  LABEL {
    uuid id PK
    tstzrange time_range
    enum label_class
    uuid taxonomy_id FK
    enum scope
    enum tier
    enum source
    enum review_status
    uuid origin_group_id FK
    uuid promoted_by FK
    string external_id
  }
  LABEL_CHANNEL {
    uuid label_id FK
    uuid channel_id FK
    string role
  }
  PLATFORM_USER {
    uuid id PK
    string username
    enum role
  }
```

**Three design points worth remembering.**

*The group is context, not identity.* `origin_group_id` records where a label
was drawn; `label_channel` records what it implicates. A label made while
viewing one group stays visible from any view of the same channels.

*Class and taxonomy are independent.* `taxonomy.allowed_classes` lets one
type carry several classes — a commanded reset is `off_nominal`, an
uncommanded one is `anomaly`. Same shape, different context.

*Tier is the gate.* Anyone creates `working` labels; only a steward promotes
to `golden`; only golden feeds production training.

---

## Models, pipelines and detection

```mermaid
erDiagram
  PIPELINE ||--o{ PIPELINE_RUN : queued_as
  PIPELINE_RUN ||--o{ NODE_OUTPUT : caches
  PIPELINE_RUN ||--o| MANIFEST : pins
  MANIFEST ||--o{ MODEL_VERSION : trained_from
  MANIFEST ||--o| MANIFEST : parent
  MODEL ||--o{ MODEL_VERSION : versions
  MODEL ||--o{ MODEL_GROUP_BINDING : bound
  TELEM_GROUP ||--o{ MODEL_GROUP_BINDING : bound
  MODEL_GROUP_BINDING ||--o| SCHEDULE : retrained_by
  MODEL_VERSION ||--o{ PREDICTION : produces
  MODEL_VERSION ||--o{ FORECAST : produces
  MODEL_VERSION ||--o{ DETECTION_RUN : used_by
  RULESET ||--o{ DETECTION_RUN : evaluated_by
  DETECTION_RUN ||--o{ LABEL : proposes
  MODEL_VERSION ||--o{ LABEL : proposes

  PIPELINE {
    uuid id PK
    string name
    string spec_uri
    string task
  }
  PIPELINE_RUN {
    uuid id PK
    uuid pipeline_id FK
    enum status
    jsonb params
    uuid manifest_id FK
    uuid requested_by
    timestamptz started_at
    timestamptz finished_at
    string error
    string log_uri
  }
  NODE_OUTPUT {
    string cache_key PK
    uuid pipeline_run_id FK
    string node_id
    string artifact_uri
    string content_hash
  }
  MANIFEST {
    uuid id PK
    string content_hash
    jsonb channel_ids
    jsonb time_ranges
    timestamptz ingest_watermark
    string transform_version
    jsonb label_filter
    uuid parent_manifest FK
  }
  MODEL {
    uuid id PK
    string name
    string algorithm
    enum task
  }
  MODEL_VERSION {
    uuid id PK
    uuid model_id FK
    int version
    uuid manifest_id FK
    string artifact_uri
    jsonb eval_metrics
    enum status
    uuid promoted_by
    double threshold
  }
  MODEL_GROUP_BINDING {
    uuid model_id FK
    uuid group_id FK
    bool is_default
  }
  SCHEDULE {
    uuid id PK
    string cadence
    int min_new_labels
    bool enabled
    timestamptz last_run
  }
  PREDICTION {
    uuid id PK
    uuid model_version_id FK
    uuid group_id FK
    tstzrange window_range
    jsonb regions
  }
  FORECAST {
    uuid id PK
    uuid model_version_id FK
    uuid channel_id FK
    timestamptz issued_at
    interval horizon
    jsonb points
  }
  RULESET {
    uuid id PK
    string name
    int version
    string content_hash
    jsonb rules
    bool active
  }
  DETECTION_RUN {
    uuid id PK
    uuid model_version_id FK
    uuid ruleset_id FK
    uuid group_id FK
    tstzrange window_range
    int n_proposed
    timestamptz created_at
  }
  LLM_CALL {
    uuid id PK
    uuid user_id
    string model
    jsonb context
    text prompt
    text response
    int latency_ms
  }
  TELEM_GROUP {
    uuid id PK
    string name
  }
  LABEL {
    uuid id PK
    enum source
    enum tier
  }
```

**What the new tables buy.**

`pipeline_run` **is the job queue.** The platform API inserts a `queued` row;
the runner polls with `FOR UPDATE SKIP LOCKED`. No broker to deploy or
accredit, and the audit trail is a side effect rather than extra work.

`node_output` **is the cache.** Key is
`hash(notebook_source, params, manifest_hash, upstream_hashes)`. Change a
training parameter and preprocessing is skipped; edit the notebook and
everything downstream invalidates. This only works because pipeline notebooks
declare their inputs.

`ruleset` **turns scores into meaning.** A model emits a number; a rule set
maps it to a class and taxonomy. Versioning it matters because changing the
rules changes what every future label means — so an auto-label traces to
exactly two hashes, one for the model and one for the rules.

`forecast` **stores what was expected.** "Predicted 12.4 ± 2.1, observed 19.8"
is only reconstructible if the prediction was kept. It also renders as a
styling variant of the existing mean-plus-band chart.

`model.task` is `anomaly_detection | anomaly_classification | forecasting`,
which is what the production model picker groups by.

`model_version.threshold` pins the decision boundary learned at training time,
so a promoted model does not depend on a within-window quantile at inference.

---

## Provenance in one query

Every artefact traces back to hashes:

```sql
SELECT m.name, v.version, v.status,
       man.content_hash AS manifest,
       man.transform_version,
       r.content_hash   AS ruleset,
       pr.id            AS pipeline_run
FROM ml.model_version v
JOIN ml.model m        ON m.id = v.model_id
LEFT JOIN ml.manifest man ON man.id = v.manifest_id
LEFT JOIN ml.detection_run d ON d.model_version_id = v.id
LEFT JOIN ml.ruleset r ON r.id = d.ruleset_id
LEFT JOIN ml.pipeline_run pr ON pr.manifest_id = man.id
WHERE v.status = 'promoted';
```

And retraining lineage is recursive over `manifest.parent_manifest`.