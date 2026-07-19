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
