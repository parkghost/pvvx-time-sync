"""Local time as pvvx devices keep it.

The firmware has no time zone or DST rules: its clock counts local wall-clock
seconds as if they were UTC, so a change of Home Assistant's UTC offset leaves
the device off by the difference until the next sync.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util

# zoneinfo does not expose its transitions; scan in steps this long. Assumes the
# offset never changes and changes back within one step.
_SCAN_STEP = timedelta(days=1)
_RESOLUTION = timedelta(seconds=1)


def utc_offset(at: datetime) -> int:
    """Offset of Home Assistant's time zone from UTC at ``at``, in seconds."""
    offset = dt_util.as_local(at).utcoffset()
    return int(offset.total_seconds()) if offset else 0


def next_offset_change(start: datetime, end: datetime, offset: int) -> datetime | None:
    """First moment in [start, end] whose UTC offset differs from ``offset``."""
    if utc_offset(start) != offset:
        return start
    low = start
    while low < end:
        high = min(low + _SCAN_STEP, end)
        if utc_offset(high) != offset:
            while high - low > _RESOLUTION:
                middle = low + (high - low) / 2
                if utc_offset(middle) != offset:
                    high = middle
                else:
                    low = middle
            return high
        low = high
    return None
