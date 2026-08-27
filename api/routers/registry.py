"""Model registry - deliberately thin.

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
    """Models, optionally scoped to those bound to a group.

    `promoted_version` is the count of currently-promoted versions (0 or 1) so
    a picker can grey out models that have nothing runnable yet, without a
    second round trip per row.
    """
    if group_id:
        return await fetch_all(
            """
            SELECT m.id, m.name, m.algorithm, m.task::text, m.description,
                   b.is_default,
                   count(v.id) FILTER (WHERE v.status = 'promoted') AS promoted_versions,
                   count(v.id) FILTER (WHERE v.status = 'candidate') AS candidate_versions
            FROM ml.model m
            JOIN ml.model_group_binding b ON b.model_id = m.id
            LEFT JOIN ml.model_version v ON v.model_id = m.id
            WHERE b.group_id = %s
            GROUP BY m.id, m.name, m.algorithm, m.task, m.description, b.is_default
            ORDER BY m.name
            """,
            (group_id,),
        )
    return await fetch_all(
        """
        SELECT m.id, m.name, m.algorithm, m.task::text, m.description,
               count(v.id) FILTER (WHERE v.status = 'promoted') AS promoted_versions,
               count(v.id) FILTER (WHERE v.status = 'candidate') AS candidate_versions
        FROM ml.model m
        LEFT JOIN ml.model_version v ON v.model_id = m.id
        GROUP BY m.id, m.name, m.algorithm, m.task, m.description
        ORDER BY m.name
        """
    )


@router.get("/models/{model_id}/versions")
async def list_versions(model_id: uuid.UUID, promoted_only: bool = False):
    """Versions of one model, newest first.

    Returns what a person needs to choose responsibly: the pinned decision
    boundary and how it was derived, the evaluation metrics, and the training
    scope carried by the manifest. `promoted_only` serves the detection-run
    picker (DET-F-08); the signoff screen leaves it false so candidates show.

    `channel_ids` and `time_ranges` are manifest jsonb, returned as-is. The
    count is precomputed because a picker wants "trained on 2 channels", not
    the array.
    """
    return await fetch_all(
        """
        SELECT v.id,
               v.version,
               v.status::text,
               v.eval_metrics,
               v.threshold,
               v.threshold_method,
               v.artifact_uri,
               v.pipeline_run_id,
               v.created_at,
               v.promoted_at,
               v.promoted_by,
               m.name        AS model_name,
               m.algorithm,
               m.task::text,
               man.content_hash,
               man.channel_ids,
               man.time_ranges,
               man.ingest_watermark,
               man.transform_version,
               jsonb_array_length(man.channel_ids) AS channel_count
        FROM ml.model_version v
        JOIN ml.model m ON m.id = v.model_id
        LEFT JOIN ml.manifest man ON man.id = v.manifest_id
        WHERE v.model_id = %s
          AND (NOT %s OR v.status = 'promoted')
        ORDER BY v.version DESC
        """,
        (model_id, promoted_only),
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