"""Telemetry groups: the analytical working set."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from ..db import execute, fetch_all, fetch_one
from ..schemas import Group, GroupCreate

router = APIRouter(prefix="/groups", tags=["groups"])


async def _members(group_id: uuid.UUID) -> list[dict]:
    return await fetch_all(
        """
        SELECT gm.channel_id, c.mnemonic, c.units, gm.display_order, gm.axis
        FROM app.group_member gm
        JOIN catalog.channel c ON c.id = gm.channel_id
        WHERE gm.group_id = %s
        ORDER BY gm.display_order, c.mnemonic
        """,
        (group_id,),
    )


@router.get("", response_model=list[Group])
async def list_groups(satellite_id: uuid.UUID | None = None):
    if satellite_id:
        rows = await fetch_all(
            "SELECT id, satellite_id, name, description FROM app.telem_group "
            "WHERE satellite_id = %s ORDER BY name",
            (satellite_id,),
        )
    else:
        rows = await fetch_all(
            "SELECT id, satellite_id, name, description FROM app.telem_group ORDER BY name"
        )
    return [Group(**row, members=await _members(row["id"])) for row in rows]


@router.post("", response_model=Group, status_code=201)
async def create_group(payload: GroupCreate):
    row = await fetch_one(
        """
        INSERT INTO app.telem_group (satellite_id, name, description)
        VALUES (%s, %s, %s)
        ON CONFLICT (satellite_id, name) DO UPDATE SET description = EXCLUDED.description
        RETURNING id, satellite_id, name, description
        """,
        (payload.satellite_id, payload.name, payload.description),
    )
    for order, channel_id in enumerate(payload.channel_ids):
        await execute(
            "INSERT INTO app.group_member (group_id, channel_id, display_order) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (row["id"], channel_id, order),
        )
    return Group(**row, members=await _members(row["id"]))


@router.get("/{group_id}", response_model=Group)
async def get_group(group_id: uuid.UUID):
    row = await fetch_one(
        "SELECT id, satellite_id, name, description FROM app.telem_group WHERE id = %s",
        (group_id,),
    )
    if not row:
        raise HTTPException(404, "group not found")
    return Group(**row, members=await _members(group_id))


@router.post("/{group_id}/members", status_code=204)
async def add_member(group_id: uuid.UUID, channel_id: uuid.UUID, axis: int = 0):
    await execute(
        "INSERT INTO app.group_member (group_id, channel_id, axis) VALUES (%s, %s, %s) "
        "ON CONFLICT (group_id, channel_id) DO UPDATE SET axis = EXCLUDED.axis",
        (group_id, channel_id, axis),
    )


@router.delete("/{group_id}/members/{channel_id}", status_code=204)
async def remove_member(group_id: uuid.UUID, channel_id: uuid.UUID):
    await execute(
        "DELETE FROM app.group_member WHERE group_id = %s AND channel_id = %s",
        (group_id, channel_id),
    )


@router.delete("/{group_id}", status_code=204)
async def delete_group(group_id: uuid.UUID):
    await execute("DELETE FROM app.telem_group WHERE id = %s", (group_id,))
