# Label governance — how to use it

Migration `013_label_governance.sql` reshapes labelling around three ideas
taken from the ESA Anomaly Detection Benchmark, whose annotations were made by
ESOC operations engineers.

## Apply it

```powershell
# platform repo
uv run python -m api.migrate
```

Idempotent — safe to re-run. Verified against Postgres 16.

---

## The three ideas

### 1. Three classes, not two

| Class | Means |
|---|---|
| `anomaly` | Unexplained deviation needing investigation |
| `off_nominal` | Known, explainable departure (commanded, expected, limit) |
| `nominal` | **Inspected and confirmed normal** |

`nominal` is the one people skip, and skipping it quietly breaks evaluation.
An unlabelled region is not "normal" — it is "nobody looked". Without explicit
nominal labels, every true negative in your precision figures is really an
unknown. ESA-ADB encodes the same three states as `0 = nominal`,
`1 = anomaly`, `2 = rare event`.

### 2. Class and type are independent

From the ESA-ADB paper: a reset caused by a telecommand is a *rare nominal
event*; an uncommanded reset is an *anomaly*. Same signal shape — the
difference is context.

So taxonomy entries declare which classes they may carry:

```sql
SELECT code, allowed_classes FROM labels.taxonomy;

 relationship_break | {anomaly}
 reset              | {anomaly,off_nominal}
 step_change        | {anomaly,off_nominal}
 reviewed_clean     | {nominal}
```

One `reset` type, two possible classes, chosen per label:

```sql
-- commanded
INSERT INTO labels.label (time_range, label_class, taxonomy_id, note)
SELECT tstzrange('2011-05-01','2011-05-02'), 'off_nominal', id, 'commanded'
FROM labels.taxonomy WHERE code = 'reset';

-- uncommanded, same type
INSERT INTO labels.label (time_range, label_class, taxonomy_id, note)
SELECT tstzrange('2012-01-01','2012-01-02'), 'anomaly', id, 'no telecommand found'
FROM labels.taxonomy WHERE code = 'reset';
```

This is also the argument for eventually ingesting telecommand history: it is
what lets the platform tell those two apart automatically.

### 3. Scope: one channel or a relationship

```
scope = 'channel'   this signal misbehaved
scope = 'group'     the relationship between several channels broke
```

Channels attach through `labels.label_channel` with a role, so a relationship
break implicates two channels while belonging to neither:

```sql
INSERT INTO labels.label_channel (label_id, channel_id, role)
VALUES (:label_id, :chan_a, 'involved'),
       (:label_id, :chan_b, 'involved');
```

**The group is context, not identity.** `origin_group_id` records where a
label was drawn; the label stays visible from any view of the same channels:

```sql
SELECT c.mnemonic, t.code, l.label_class, l.scope
FROM labels.label l
JOIN labels.label_channel lc ON lc.label_id = l.id
JOIN catalog.channel c ON c.id = lc.channel_id
LEFT JOIN labels.taxonomy t ON t.id = l.taxonomy_id
WHERE c.mnemonic = 'AMT00102';
```

---

## Governance: freedom at the edge, a gate before it matters

```
                       anyone                    steward only
  draw a label  ──►  tier = working  ──────────►  tier = golden  ──►  training
                     (edit freely)                (curated truth)
```

| Role | May |
|---|---|
| `viewer` | read |
| `analyst` | create and edit working labels, propose taxonomy terms |
| `steward` | promote labels to golden, approve taxonomy terms |
| `admin` | everything, plus users |

Analysts are unconstrained because constraining exploration just makes people
stop using the tool. A wrong working label costs nothing — it never reaches a
model. What *is* governed is the taxonomy (free text drifts into "weird",
"spike?", "check this") and entry into the golden set.

### Promote to golden

```sql
UPDATE labels.label
SET tier = 'golden',
    promoted_by = :steward_user_id,
    promoted_at = now()
WHERE id = :label_id
  AND review_status = 'accepted';
```

### What training reads

```sql
SELECT * FROM labels.golden_label;
```

The view enforces both invariants at once:

```sql
WHERE l.tier = 'golden' AND l.review_status = 'accepted'
```

So a model proposal (`source = 'model'`, `review_status = 'proposed'`) can
never become training data without a human accepting *and* a steward promoting
it. That is the echo-chamber guard made structural rather than procedural.

### Proposing a new taxonomy term

```sql
INSERT INTO labels.taxonomy (code, name, allowed_classes, approved, proposed_by)
VALUES ('thruster_signature', 'Thruster firing signature',
        ARRAY['off_nominal'], false, :analyst_id);
```

`approved = false` keeps it out of the default picker until a steward flips it.

---

## Seeded taxonomy

| Code | Allowed classes |
|---|---|
| `point_anomaly` | anomaly |
| `subsequence_anomaly` | anomaly |
| `relationship_break` | anomaly |
| `step_change` | anomaly, off_nominal |
| `drift` | anomaly, off_nominal |
| `reset` | anomaly, off_nominal |
| `mode_transition` | off_nominal |
| `limit_violation` | off_nominal, anomaly |
| `communication_gap` | off_nominal |
| `rare_nominal_event` | off_nominal |
| `reviewed_clean` | nominal |

Three seeds from migration 011 (`unexplained_deviation`, `expected_event`,
`data_gap`) are deactivated if unused, since the richer set replaces them.

---

## Importing ESA-ADB ground truth

`source = 'imported'` plus `external_id` keeps benchmark labels separable from
your analysts' work — train on one, evaluate on the other, without
contamination:

```sql
INSERT INTO labels.label
  (time_range, label_class, taxonomy_id, scope, tier, source, external_id, review_status)
VALUES (tstzrange(:start, :end), 'anomaly', :taxonomy_id, 'channel',
        'golden', 'imported', :esa_adb_id, 'accepted');
```

---

## What still needs building

- API endpoints for `scope`, `tier`, `label_channel`, and promotion
- A steward review queue in the UI
- Role enforcement (the schema models roles; nothing checks them yet)