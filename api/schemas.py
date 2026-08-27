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
    """One rendered point.

    For aggregate tiers this summarises a whole bucket: v is the mean, lo/hi
    the extremes, p05/p95 the 5th and 95th percentiles, and n how many raw
    readings were aggregated. All are null for the raw tier except v.
    """

    t: dt.datetime
    v: float | None = None
    lo: float | None = None
    hi: float | None = None
    p05: float | None = None
    p95: float | None = None
    n: int | None = None


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
    """A label drawn by a human.

    Deliberately cannot express a model proposal. There is no `review_status`,
    `tier`, `source`, or attribution field here: the server sets all of them.
    Proposals are written by the detection run (see `create_proposals`), where
    attribution comes from the run itself rather than from a client claim.
    """

    group_id: uuid.UUID
    start: dt.datetime
    end: dt.datetime
    label_class: str = Field(pattern="^(anomaly|off_nominal|nominal)$")
    taxonomy_code: str
    channel_ids: list[uuid.UUID] = []
    scope: str = Field(default="channel", pattern="^(channel|group)$")
    severity: int | None = Field(default=None, ge=1, le=5)
    note: str | None = None
    missed: bool = False
    """True when the analyst is marking something a scored model failed to
    propose. Counts as a false negative; only meaningful inside a detection
    run's window."""


class LabelReview(BaseModel):
    """An analyst's verdict on a model proposal."""

    review_status: str = Field(pattern="^(accepted|rejected)$")
    note: str | None = None


class ProposedRegion(BaseModel):
    """One region a detection run wants a human to look at."""

    start: dt.datetime
    end: dt.datetime
    label_class: str = Field(pattern="^(anomaly|off_nominal|nominal)$")
    taxonomy_code: str
    channel_ids: list[uuid.UUID] = []
    scope: str = Field(default="channel", pattern="^(channel|group)$")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    severity: int | None = Field(default=None, ge=1, le=5)
    note: str | None = None


class Label(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID | None = None
    channel_ids: list[uuid.UUID] = []
    start: dt.datetime
    end: dt.datetime
    label_class: str
    scope: str
    tier: str
    source: str
    taxonomy_code: str | None = None
    taxonomy_name: str | None = None
    color: str | None = None
    review_status: str
    severity: int | None = None
    confidence: float | None = None
    note: str | None = None
    # Provenance. Null for human labels; all three set for model proposals.
    proposed_by_version: uuid.UUID | None = None
    detection_run_id: uuid.UUID | None = None
    ruleset_id: uuid.UUID | None = None
    author_id: uuid.UUID | None = None
    reviewed_by: uuid.UUID | None = None
    reviewed_at: dt.datetime | None = None
    promoted_by: uuid.UUID | None = None
    promoted_at: dt.datetime | None = None
    # Resolved from proposed_by_version so a client can group and filter by
    # detector without holding a uuid-to-name map of its own.
    model_name: str | None = None
    algorithm: str | None = None
    model_version: int | None = None
    created_at: dt.datetime


class TaxonomyItem(BaseModel):
    """Taxonomy no longer belongs to a class.

    Migration 013 dropped `taxonomy.label_class` in favour of
    `allowed_classes`, because the same event type can be an anomaly or an
    expected nominal event depending on context - a commanded reset versus an
    uncommanded one.
    """

    id: uuid.UUID
    code: str
    name: str
    allowed_classes: list[str]
    parent_code: str | None = None
    description: str | None = None
    color: str | None = None
    approved: bool = True