"""Labels: regions drawn by a human, or proposed by a model and reviewed.

This is the feedback loop. Accepted golden labels are what a retrain manifest
consumes; rejected ones feed precision. Model output never becomes training
data without a human touching it.

**Write paths are split by origin, deliberately.**

`POST /labels` is the human path only. It cannot express a proposal: the
server fixes `source='human'`, `tier='working'` and the review status, and the
request body carries no attribution fields. A client cannot claim that a
region came from a model.

Model proposals are written by `create_proposals()`, which is *not* an HTTP
route. The detection run calls it alongside the insert into `ml.detection_run`,
so `detection_run_id`, `proposed_by_version` and `ruleset_id` come from the run
itself. That is what makes DET-NF-01 hold - every auto-label traces to exactly
two hashes - rather than depending on a caller to fill the fields in honestly.

Verification is `PATCH /labels/{id}/review`, which records who decided and
when. Promotion to the golden tier is a separate steward action.
"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException, Query
from psycopg.types.range import TimestamptzRange

from ..db import execute, fetch_all, fetch_one, pool
from ..schemas import Label, LabelCreate, LabelReview, ProposedRegion, TaxonomyItem

router = APIRouter(prefix="/labels", tags=["labels"])

# l.id and t.id are primary keys, so Postgres lets every other column of those
# tables ride along in the GROUP BY by functional dependency.
SELECT_SQL = """
SELECT l.id,
       l.origin_group_id AS group_id,
       lower(l.time_range) AS start, upper(l.time_range) AS "end",
       l.label_class::text, l.scope::text, l.tier::text, l.source::text,
       t.code AS taxonomy_code, t.name AS taxonomy_name, t.color,
       l.review_status::text, l.severity, l.confidence, l.note,
       l.proposed_by_version, l.detection_run_id, l.ruleset_id,
       l.author_id, l.reviewed_by, l.reviewed_at,
       l.promoted_by, l.promoted_at, l.created_at,
       -- what produced this, in words. proposed_by_version is a uuid, which is
       -- useless in a filter: "show me only the ruptures findings" has to be
       -- answerable without the caller first resolving ids to names.
       m.name AS model_name, m.algorithm, mv.version AS model_version,
       COALESCE(array_remove(array_agg(lc.channel_id), NULL), '{}') AS channel_ids
FROM labels.label l
LEFT JOIN labels.taxonomy t ON t.id = l.taxonomy_id
LEFT JOIN labels.label_channel lc ON lc.label_id = l.id
LEFT JOIN ml.model_version mv ON mv.id = l.proposed_by_version
LEFT JOIN ml.model m ON m.id = mv.model_id
"""

# mv.id and m.id are primary keys, so their other columns ride along too.
GROUP_BY = " GROUP BY l.id, t.id, mv.id, m.id "


async def _one(label_id: uuid.UUID) -> dict:
    rows = await fetch_all(SELECT_SQL + " WHERE l.id = %s" + GROUP_BY, (label_id,))
    if not rows:
        raise HTTPException(404, "label not found")
    return rows[0]


async def _resolve_taxonomy(code: str, label_class: str) -> uuid.UUID:
    """Look up a taxonomy entry and check the class is one it may carry.

    Migration 013 made class and type independent: `reset` may be an anomaly
    or off-nominal depending on whether it was commanded, but `mode_transition`
    may only ever be off-nominal. `allowed_classes` is what encodes that, and
    it is enforced here rather than trusted from the client.
    """
    row = await fetch_one(
        "SELECT id, allowed_classes FROM labels.taxonomy "
        "WHERE code = %s AND active AND approved",
        (code,),
    )
    if not row:
        raise HTTPException(400, f"unknown or inactive taxonomy code {code!r}")
    if label_class not in row["allowed_classes"]:
        raise HTTPException(
            400,
            f"taxonomy {code!r} may not carry class {label_class!r} "
            f"(allowed: {', '.join(row['allowed_classes'])})",
        )
    return row["id"]


@router.get("/taxonomy", response_model=list[TaxonomyItem])
async def list_taxonomy(include_unapproved: bool = False):
    """The controlled vocabulary.

    Only approved entries by default: a steward-proposed term should be visible
    in a governance screen but not in an analyst's picker.
    """
    return await fetch_all(
        """
        SELECT id, code, name, allowed_classes, parent_code,
               description, color, approved
        FROM labels.taxonomy
        WHERE active AND (approved OR %s)
        ORDER BY name
        """,
        (include_unapproved,),
    )


@router.get("", response_model=list[Label])
async def list_labels(
    group_id: uuid.UUID,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    review_status: str | None = Query(None),
    tier: str | None = Query(None, pattern="^(working|golden)$"),
    source: str | None = Query(None, pattern="^(human|model|rule|imported)$"),
    taxonomy_code: str | None = Query(None),
    algorithm: str | None = Query(None),
    model_name: str | None = Query(None),
    min_confidence: float | None = Query(None, ge=0.0, le=1.0),
):
    """Labels relevant to a group.

    Relevance is by channel overlap, not just origin. Migration 013 made
    `group_id` optional precisely because the group a label was drawn in is
    context rather than identity: a label made while viewing one group must
    stay visible from any other view of the same channels.
    """
    where = [
        """(l.origin_group_id = %s
            OR EXISTS (SELECT 1
                       FROM labels.label_channel lc2
                       JOIN app.group_member gm ON gm.channel_id = lc2.channel_id
                       WHERE lc2.label_id = l.id AND gm.group_id = %s))"""
    ]
    params: list = [group_id, group_id]
    if start and end:
        where.append("l.time_range && tstzrange(%s, %s)")
        params.extend([start, end])
    if review_status:
        where.append("l.review_status = %s")
        params.append(review_status)
    if tier:
        where.append("l.tier = %s")
        params.append(tier)
    if source:
        where.append("l.source = %s")
        params.append(source)
    if taxonomy_code:
        where.append("t.code = %s")
        params.append(taxonomy_code)
    if algorithm:
        where.append("m.algorithm = %s")
        params.append(algorithm)
    if model_name:
        where.append("m.name = %s")
        params.append(model_name)
    if min_confidence is not None:
        # a human label has no confidence and must not be filtered away by a
        # threshold that only means anything for a scored proposal
        where.append("(l.confidence IS NULL OR l.confidence >= %s)")
        params.append(min_confidence)
    return await fetch_all(
        SELECT_SQL
        + " WHERE "
        + " AND ".join(where)
        + GROUP_BY
        + " ORDER BY lower(l.time_range)",
        tuple(params),
    )


@router.post("", response_model=Label, status_code=201)
async def create_label(
    payload: LabelCreate,
    # TODO: replace with the authenticated principal once auth lands. Taking
    # identity from the client is a stopgap and must not survive accreditation.
    author_id: uuid.UUID | None = Query(None),
):
    """Create a human-drawn label.

    Always `source='human'` and `tier='working'`. Anyone may label freely;
    nothing an analyst does here can reach production training data, because
    only a steward promotes to golden.

    `missed=true` records a region the model failed to propose - a false
    negative. It is set at creation because there is no proposal row to patch:
    the model never produced one. That is why `missed` is not a valid target
    for the review endpoint.
    """
    if payload.end <= payload.start:
        raise HTTPException(400, "end must be after start")
    if payload.scope == "channel" and len(payload.channel_ids) != 1:
        raise HTTPException(400, "channel-scoped labels need exactly one channel")
    if payload.scope == "group" and len(payload.channel_ids) < 2:
        raise HTTPException(400, "group-scoped labels need at least two channels")

    taxonomy_id = await _resolve_taxonomy(payload.taxonomy_code, payload.label_class)
    review_status = "missed" if payload.missed else "accepted"
    legacy_channel = payload.channel_ids[0] if len(payload.channel_ids) == 1 else None

    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO labels.label
                    (origin_group_id, group_id, channel_id, time_range,
                     label_class, taxonomy_id, scope, tier, source,
                     review_status, severity, note, author_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'working', 'human',
                        %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    payload.group_id,
                    payload.group_id,
                    legacy_channel,
                    TimestamptzRange(payload.start, payload.end, "[)"),
                    payload.label_class,
                    taxonomy_id,
                    payload.scope,
                    review_status,
                    payload.severity,
                    payload.note,
                    author_id,
                ),
            )
            label_id = (await cur.fetchone())["id"]
            for channel_id in payload.channel_ids:
                await cur.execute(
                    "INSERT INTO labels.label_channel (label_id, channel_id, role) "
                    "VALUES (%s, %s, 'primary') ON CONFLICT DO NOTHING",
                    (label_id, channel_id),
                )

    return await _one(label_id)


@router.patch("/{label_id}/review", response_model=Label)
async def review_label(
    label_id: uuid.UUID,
    verdict: LabelReview,
    # TODO: from the authenticated principal, as above.
    reviewer_id: uuid.UUID | None = Query(None),
):
    """Accept or reject a model proposal.

    Only proposals are reviewable. A human-drawn label is already its author's
    verdict, and re-deciding it here would silently rewrite the precision
    figures. `proposed_by_version` is left untouched on accept: that link is
    what makes an accepted proposal count as a true positive later.
    """
    row = await fetch_one(
        "SELECT review_status::text FROM labels.label WHERE id = %s", (label_id,)
    )
    if not row:
        raise HTTPException(404, "label not found")
    if row["review_status"] != "proposed":
        raise HTTPException(
            409,
            "only proposed labels can be reviewed "
            f"(this one is {row['review_status']!r})",
        )

    await execute(
        """
        UPDATE labels.label
           SET review_status = %s,
               reviewed_by    = %s,
               reviewed_at    = now(),
               note           = COALESCE(%s, note),
               updated_at     = now()
         WHERE id = %s
        """,
        (verdict.review_status, reviewer_id, verdict.note, label_id),
    )
    return await _one(label_id)


@router.post("/{label_id}/promote", response_model=Label)
async def promote_label(
    label_id: uuid.UUID,
    # TODO: must be a steward once app.user_role is enforced.
    steward_id: uuid.UUID | None = Query(None),
):
    """Promote a working label into the golden tier.

    The gate on training data. `labels.golden_label` reads only accepted,
    golden-tier rows, so this is the single action that lets a label influence
    a production model.
    """
    row = await fetch_one(
        "SELECT review_status::text, tier::text FROM labels.label WHERE id = %s",
        (label_id,),
    )
    if not row:
        raise HTTPException(404, "label not found")
    if row["review_status"] not in {"accepted", "missed"}:
        raise HTTPException(409, "only accepted or missed labels can be promoted")
    if row["tier"] == "golden":
        raise HTTPException(409, "already golden")

    await execute(
        "UPDATE labels.label SET tier = 'golden', promoted_by = %s, "
        "promoted_at = now(), updated_at = now() WHERE id = %s",
        (steward_id, label_id),
    )
    return await _one(label_id)


@router.delete("/{label_id}", status_code=204)
async def delete_label(label_id: uuid.UUID):
    row = await fetch_one(
        "SELECT tier::text FROM labels.label WHERE id = %s", (label_id,)
    )
    if row and row["tier"] == "golden":
        raise HTTPException(
            409, "golden labels cannot be deleted; demote or retire instead"
        )
    await execute("DELETE FROM labels.label WHERE id = %s", (label_id,))


# ---------------------------------------------------------------------------
# Not an HTTP route
# ---------------------------------------------------------------------------
async def create_proposals(
    *,
    detection_run_id: uuid.UUID,
    model_version_id: uuid.UUID,
    ruleset_id: uuid.UUID | None,
    group_id: uuid.UUID,
    regions: list[ProposedRegion],
) -> list[uuid.UUID]:
    """Write the regions a detection run proposes, as `proposed` labels.

    Called by the detection run, never exposed over HTTP. Attribution comes
    from the run's own identifiers rather than from a request body, so a
    proposal cannot exist without the two hashes that explain it.

    Everything lands as `tier='working'`: a proposal is not training data, and
    it does not become training data by being accepted either - a steward still
    has to promote it.
    """
    created: list[uuid.UUID] = []
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            for region in regions:
                if region.end <= region.start:
                    raise ValueError(f"region ends before it starts: {region!r}")
                await cur.execute(
                    "SELECT id, allowed_classes FROM labels.taxonomy "
                    "WHERE code = %s AND active",
                    (region.taxonomy_code,),
                )
                tax = await cur.fetchone()
                if not tax:
                    raise ValueError(f"unknown taxonomy code {region.taxonomy_code!r}")
                if region.label_class not in tax["allowed_classes"]:
                    raise ValueError(
                        f"taxonomy {region.taxonomy_code!r} may not carry class "
                        f"{region.label_class!r}"
                    )

                legacy_channel = (
                    region.channel_ids[0] if len(region.channel_ids) == 1 else None
                )
                await cur.execute(
                    """
                    INSERT INTO labels.label
                        (origin_group_id, group_id, channel_id, time_range,
                         label_class, taxonomy_id, scope, tier, source,
                         review_status, severity, confidence, note,
                         proposed_by_version, detection_run_id, ruleset_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'working', 'model',
                            'proposed', %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        group_id,
                        group_id,
                        legacy_channel,
                        TimestamptzRange(region.start, region.end, "[)"),
                        region.label_class,
                        tax["id"],
                        region.scope,
                        region.severity,
                        region.confidence,
                        region.note,
                        model_version_id,
                        detection_run_id,
                        ruleset_id,
                    ),
                )
                label_id = (await cur.fetchone())["id"]
                created.append(label_id)
                for channel_id in region.channel_ids:
                    await cur.execute(
                        "INSERT INTO labels.label_channel "
                        "(label_id, channel_id, role) VALUES (%s, %s, 'primary') "
                        "ON CONFLICT DO NOTHING",
                        (label_id, channel_id),
                    )
    return created