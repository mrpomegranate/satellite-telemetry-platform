"""Tier selection is the load-bearing performance decision; test it directly."""
import datetime as dt

from api.tiers import pick_tier

MAX = 2000


def window(**kwargs) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime(2010, 1, 1, tzinfo=dt.timezone.utc)
    return start, start + dt.timedelta(**kwargs)


def test_short_window_uses_raw():
    bucket, name = pick_tier(*window(minutes=20), MAX)
    assert (bucket, name) == (None, "raw")


def test_multi_day_window_uses_10min():
    bucket, name = pick_tier(*window(days=7), MAX)
    assert (bucket, name) == (600, "10min")


def test_mission_span_uses_6h():
    bucket, name = pick_tier(*window(days=1600), MAX)
    assert (bucket, name) == (21600, "6h")


def test_never_exceeds_budget_when_possible():
    start, end = window(days=7)
    bucket, _ = pick_tier(start, end, MAX)
    assert (end - start).total_seconds() / (bucket or 1) <= MAX
