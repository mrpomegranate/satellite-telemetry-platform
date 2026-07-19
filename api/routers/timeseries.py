"""Windowed telemetry reads with automatic resolution switching."""
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
