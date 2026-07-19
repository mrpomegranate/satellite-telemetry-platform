"""Labels: regions drawn by a human, or proposed by a model and reviewed.

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
