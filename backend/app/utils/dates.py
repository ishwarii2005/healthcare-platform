"""
Every datetime stored in this app is created with datetime.utcnow() - naive, but
always UTC. Python's default .isoformat() on a naive datetime omits the timezone
entirely (e.g. "2026-07-13T10:05:00"), which browsers then parse as *local* time,
not UTC - silently shifting every timestamp by the user's UTC offset. This helper
is the single place that fixes that: it stamps the value as UTC before formatting,
so the frontend always receives an unambiguous "+00:00" offset it can parse correctly
regardless of the browser's local timezone.
"""
from datetime import datetime, timezone


def to_utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
