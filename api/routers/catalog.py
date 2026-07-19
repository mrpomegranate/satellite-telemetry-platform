"""Catalog navigation: satellites, subsystems, channel search.

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
