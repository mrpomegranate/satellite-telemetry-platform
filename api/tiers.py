"""Resolution selection.

The browser never receives more than `max_points` per channel. Given a window,
pick the finest tier that still fits, then read the matching table. This is why
the chart stays fast without WASM: the point count is capped server-side
regardless of how much data exists.
"""
from __future__ import annotations

import datetime as dt

# (bucket seconds, tier name). None bucket = raw samples.
TIERS: list[tuple[int | None, str]] = [
    (None, "raw"),
    (600, "10min"),
    (21600, "6h"),
]

RAW_ASSUMED_SECONDS = 1


def pick_tier(start: dt.datetime, end: dt.datetime, max_points: int) -> tuple[int | None, str]:
    """Finest tier whose point count fits the budget; coarsest as fallback."""
    span = max((end - start).total_seconds(), 1.0)
    for bucket, name in TIERS:
        effective = bucket or RAW_ASSUMED_SECONDS
        if span / effective <= max_points:
            return bucket, name
    return TIERS[-1]
