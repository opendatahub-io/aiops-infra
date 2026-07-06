"""Date parsing utilities shared across conforma scripts."""

from __future__ import annotations

from datetime import datetime, timezone


def parse_date(date_str: str) -> datetime | None:
    """Parse a date string into a timezone-aware datetime."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
