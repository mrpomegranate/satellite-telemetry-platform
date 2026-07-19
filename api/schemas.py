"""Pydantic request/response models."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field


class Satellite(BaseModel):
    id: uuid.UUID
    designator: str
    bus_design: str | None = None
    launch_date: dt.date | None = None


class Subsystem(BaseModel):
    id: uuid.UUID
    satellite_id: uuid.UUID
    code: str
    name: str | None = None
    channel_count: int | None = None


class Channel(BaseModel):
    id: uuid.UUID
    subsystem_id: uuid.UUID
    subsystem_code: str | None = None
    mnemonic: str
    display_name: str | None = None
    units: str | None = None
    sample_rate: str | None = None


class Point(BaseModel):
    """One rendered point. Envelope fields are null for the raw tier."""

    t: dt.datetime
    v: float | None = None
    lo: float | None = None
    hi: float | None = None
    p05: float | None = None
    p95: float | None = None


class Series(BaseModel):
    channel_id: uuid.UUID
    mnemonic: str
    units: str | None = None
    tier: str
    bucket_seconds: int | None = None
    points: list[Point]


class TimeseriesResponse(BaseModel):
    start: dt.datetime
    end: dt.datetime
    tier: str
    series: list[Series]


class GroupCreate(BaseModel):
    satellite_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    channel_ids: list[uuid.UUID] = []


class GroupMember(BaseModel):
    channel_id: uuid.UUID
    mnemonic: str
    units: str | None = None
    display_order: int = 0
    axis: int = 0


class Group(BaseModel):
    id: uuid.UUID
    satellite_id: uuid.UUID
    name: str
    description: str | None = None
    members: list[GroupMember] = []


class LabelCreate(BaseModel):
    group_id: uuid.UUID
    start: dt.datetime
    end: dt.datetime
    label_class: str = Field(pattern="^(anomaly|off_nominal)$")
    taxonomy_code: str | None = None
    channel_id: uuid.UUID | None = None
    note: str | None = None
    review_status: str = "accepted"


class Label(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    channel_id: uuid.UUID | None = None
    start: dt.datetime
    end: dt.datetime
    label_class: str
    taxonomy_code: str | None = None
    taxonomy_name: str | None = None
    color: str | None = None
    review_status: str
    note: str | None = None
    created_at: dt.datetime


class TaxonomyItem(BaseModel):
    id: uuid.UUID
    label_class: str
    code: str
    name: str
    description: str | None = None
    color: str | None = None
