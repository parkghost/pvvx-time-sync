"""Tests for UTC offset tracking."""

from datetime import UTC, datetime, timedelta

from custom_components.pvvx_time_sync.local_time import next_offset_change, utc_offset
from homeassistant.core import HomeAssistant

CEST = 2 * 3600
CET = 3600
# Central European Summer Time ends on 2026-10-25 at 03:00 CEST.
FALL_BACK = datetime(2026, 10, 25, 1, tzinfo=UTC)


async def test_finds_dst_end(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    start = FALL_BACK - timedelta(days=5, minutes=17)
    assert utc_offset(start) == CEST

    change = next_offset_change(start, start + timedelta(days=7), CEST)

    assert change is not None
    assert FALL_BACK <= change < FALL_BACK + timedelta(seconds=1)
    assert utc_offset(change) == CET


async def test_change_after_end_is_ignored(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    start = FALL_BACK - timedelta(days=5)
    assert next_offset_change(start, FALL_BACK - timedelta(seconds=1), CEST) is None


async def test_differing_offset_changes_at_start(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    start = FALL_BACK + timedelta(hours=1)
    assert next_offset_change(start, start + timedelta(days=1), CEST) == start


async def test_zone_without_dst_never_changes(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Asia/Taipei")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    assert next_offset_change(start, start + timedelta(days=365), 8 * 3600) is None
