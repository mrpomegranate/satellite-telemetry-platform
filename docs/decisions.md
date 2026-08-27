# DR-001 — Boundary between model development and the UI platform

**Status:** accepted
**Date:** 2026-08-26
**Affects:** `satellite-telemetry-platform`, `satellite-telemetry-mlflow`
**Supersedes:** nothing
**Related:** platform_requirements_brainstorm.md (§2 Functional, §2 Non-Functional, §4 Negotiation)

---

## Decision

Model hyperparameters are **not** exposed in the UI. Model development happens
in `satellite-telemetry-mlflow`; the UI platform consumes the result.

The UI's reach over a model is limited to three things:

1. **Selecting** a registered model version.
2. **Promoting** a candidate version to production (the human gate).
3. **Scoping** a run — which group, which time window, which ruleset.

A user who wants to change `contamination`, `pen`, `min_size`, or any other
model parameter uses the training repo, trains a version, and registers it as a
candidate. The UI then sees it.

---

## Context

The platform serves two populations with different needs:

| | Model developers | Ops analysts |
|---|---|---|
| Tooling | marimo notebooks, `sat_ml` SDK, YAML pipelines | the web UI |
| Wants | control over algorithm and parameters | to run a trusted model and review what it proposes |
| Comfortable in code | yes | not necessarily |

Exposing model parameters in the UI would serve neither group well. Developers
already have a better interface. Analysts do not want to tune `min_size`, and a
parameter panel is a fast way to rebuild the confusing UI this project exists to
replace.

The accreditation argument is stronger still. The governance principle across
both repos is *freedom at the edge, contract at the gate*. A UI that lets any
user tune parameters and promote the result puts the freedom **at** the gate,
and forces the audit trail to reconstruct what git history would have provided
for free.

### The codebase already assumed this

Two existing artifacts encode the decision and are now confirmed as intentional
rather than incidental:

- `pipelines/amt_anomaly.yaml` — "YAML in git is the source of truth."
- `runner/execute.py` — `node_params = {**params, **(node.get("params") or {})}`
  YAML node params **override** run params, so a queued run cannot change a
  parameter the pipeline declares. This is correct under DR-001 and must be
  documented in place so it is not later "fixed" as a merge-order bug.

---

## The three parameter classes

The boundary is drawn by classifying every knob, not by classifying every user.

| Class | Examples | Lives in | Changed by |
|---|---|---|---|
| **Model** | `contamination`, `pen`, `model="l2"`, `min_size` | pipeline YAML in git | code change + review + retrain |
| **Decision** | score threshold, ruleset rules | `ml.model_version.threshold`, `ml.ruleset.rules` | pinned at training; rules versioned as data |
| **Scope** | group, channels, time window, tier, which version | `ml.detection_run`, request params | the UI, freely |

Rationale for the middle row: `ml.ruleset.rules` is jsonb specifically so edits
are data rather than code deploys, and rulesets carry a `content_hash` and
version because changing a rule changes what every future label means. That
gives UI ergonomics without losing provenance. Thresholds are the opposite case
— `014_pipelines_and_detection.sql` pins them at training time so a promoted
model does not depend on a within-window quantile at inference.

---

## Derived requirements

### Functional

| ID | Requirement |
|---|---|
| **DET-F-01** | The platform shall list registered model versions, including candidates, with version number, status, algorithm, task, eval metrics, pinned threshold, manifest content hash, and promotion timestamp. |
| **DET-F-02** | The platform shall allow an authorised user to promote a candidate version to `promoted`, retiring the previously promoted version of the same model. |
| **DET-F-03** | The platform shall allow a user to request a detection run by specifying a promoted model version, a telemetry group, a time window, and a ruleset. |
| **DET-F-04** | The platform shall record every detection run in `ml.detection_run` with the model version, ruleset, group, window, trigger, and counts of scored and proposed regions. |
| **DET-F-05** | The platform shall render regions proposed by a detection run in the interval panel alongside analyst-drawn intervals, visually distinguished by origin. |
| **DET-F-06** | The platform shall allow an analyst to accept, reject, or mark-missed each proposed region, persisting the outcome to `labels.label` with `detection_run_id` and `ruleset_id` set. |
| **DET-F-07** | The platform shall **not** expose model hyperparameters for editing in any user-facing surface. |
| **DET-F-08** | The platform shall permit detection runs only against model versions with status `promoted`. |

### Non-functional

| ID | Requirement |
|---|---|
| **DET-NF-01** | *Traceability.* Every auto-generated label shall be attributable to exactly two hashes: the model version that scored it and the ruleset version that classified it. |
| **DET-NF-02** | *Provenance.* Every promoted model version shall be traceable to a manifest content hash and a pipeline run, and thence to a reviewed pipeline spec in version control. |
| **DET-NF-03** | *Auditability.* Promotion shall record the acting user and timestamp. |
| **DET-NF-04** | *Reproducibility.* A promoted model's decision boundary shall be fixed at training time and shall not depend on the distribution of the window being scored. |
| **DET-NF-05** | *Latency.* Detection over a group and window shall not block a UI request; the user shall be able to leave the page and return to a completed run. |

### Explicitly out of scope for v1

- Model parameter forms, sliders, or wizards of any kind.
- A live threshold slider on the chart.
- In-UI training or hyperparameter sweeps.
- A visual pipeline canvas that edits YAML (noted as a future direction in
  `amt_anomaly.yaml`; not v1).

---

## Consequences

**Simplifies.** No per-detector parameter schema, no schema-driven form
generation, no jargon-to-intent translation layer, no validation of mutually
exclusive parameters (e.g. ruptures' `n_bkps` / `pen` / `epsilon`). Each of
these was a recurring maintenance cost per algorithm added.

**Adds.** The registry API is currently too thin to choose a model with —
`GET /registry/models` returns id, name, and algorithm only. DET-F-01 requires
extending it; `ml.production_model` is close to the needed query.

**Constrains.** Adding a new detector (ruptures, rolling z-score) becomes a
change in the training repo — a pipeline YAML plus a pipeline notebook —
followed by registration and promotion. It is not a platform code change. This
is the intended property.

**Open risk.** If model developers find the training-repo loop too slow,
pressure to expose parameters will return. Mitigation is to keep
`notebooks/scratch/` genuinely unconstrained and to make the platform a good
*viewer* during model development, rather than to relax DR-001.

---

## Open questions

**OQ-1 — Does inference use the same queue as training?**
`ml.pipeline_run` is the queue and `runner/worker.py` claims from it, but
`ml.detection_run` has no queue path. Two options:

- *Scoring is a pipeline.* A YAML graph whose nodes load a promoted version,
  score a window, apply the ruleset, and write `detection_run` plus proposed
  labels. One queue, one worker, one audit trail, one execution path to
  accredit.
- *Separate inference path in the platform API.* Less machinery, but a second
  execution route inside the accreditation boundary.

Recommendation: the first. Decide before building the enqueue endpoint.

**OQ-2 — Is `model_group_binding` advisory or enforced?**
A version trained on one channel set should arguably not be runnable against an
unrelated group. Currently the binding is only used as a filter. Decide whether
the enqueue endpoint rejects unbound pairings (hard constraint) or merely
defaults to bound ones (UI convenience). Affects DET-F-03.

**OQ-3 — Is ruleset editing in v1?**
Recommendation: no. v1 ships one seeded default ruleset, and the entire v1 UI
surface is *pick a promoted model, pick a window, run, review proposals*. Rule
editing is a later increment once there is evidence of what analysts want to
change.

**OQ-4 — Who may promote?**
DET-F-02 says "authorised user." The role is not yet defined. Likely the same
steward role that promotes working labels to golden in `013`, but that should be
confirmed rather than assumed.

---

## Changes to make in code

Small, and worth doing before migration `015`:

1. Comment the merge order in `runner/execute.py` explaining that YAML wins by
   design, citing DR-001.
2. Extend `GET /registry/models` and `/models/{id}/versions` per DET-F-01.
3. Record `promoted_by` in `POST /registry/versions/{id}/promote` — the column
   exists in `012_ml.sql` and is currently never written.