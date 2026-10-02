"""Tests for scheduling, entities and persistence."""

import asyncio
from collections.abc import Generator
from dataclasses import replace
from datetime import timedelta
import time
from typing import Any
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.pvvx_time_sync import (
    coordinator as coordinator_module,
    local_clock,
    make_connect,
)
from custom_components.pvvx_time_sync.client import (
    DeviceDetails,
    NotPvvxDeviceError,
    PvvxClient,
    SyncResult,
)
from custom_components.pvvx_time_sync.const import DOMAIN
from custom_components.pvvx_time_sync.protocol import PvvxError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.util import dt as dt_util

from .common import ADDRESS, add_bthome_device, config_entry

pytestmark = pytest.mark.usefixtures("enable_bluetooth")

OK = SyncResult(
    details=DeviceDetails(model="MJWSD05MMC", firmware="5.9", has_hardware_clock=True),
    drift_seconds=3,
    written_local_seconds=0,
)


@pytest.fixture(autouse=True)
def device_in_range() -> Generator[None]:
    """No startup spread, and a connectable adapter sees the device."""
    with (
        patch.object(coordinator_module, "STARTUP_SPREAD_SECONDS", 0),
        patch.object(
            coordinator_module.bluetooth, "async_address_present", return_value=True
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def far_from_dst_change(freezer: FrozenDateTimeFactory) -> None:
    """Schedules span weeks; keep US/Pacific DST changes out of them."""
    freezer.move_to("2026-06-01T12:00:00+00:00")


@pytest.fixture
def sync_time() -> Generator[AsyncMock]:
    with patch.object(PvvxClient, "sync_time", AsyncMock(return_value=OK)) as mock:
        yield mock


async def setup(
    hass: HomeAssistant, entry: MockConfigEntry | None = None
) -> MockConfigEntry:
    entry = entry or config_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    registry = er.async_get(hass)
    found = registry.async_get_entity_id(platform, DOMAIN, f"{ADDRESS}_{key}")
    assert found
    return found


async def advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta
) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_first_auto_sync_runs_shortly_after_setup(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    sync_time: AsyncMock,
    hass_storage: dict[str, Any],
) -> None:
    entry = await setup(hass)
    drift = entity_id(hass, "sensor", "drift")
    assert hass.states.get(drift).state == STATE_UNKNOWN
    assert hass.states.get(entity_id(hass, "switch", "auto_sync")).state == STATE_ON

    await advance(hass, freezer, timedelta(seconds=31))

    sync_time.assert_awaited_once_with()
    assert hass.states.get(drift).state == "3"
    assert (
        hass.states.get(entity_id(hass, "sensor", "last_sync")).state != STATE_UNKNOWN
    )
    assert hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]["drift_seconds"] == 3

    # Next run follows the interval: 168 h for a hardware clock.
    await advance(hass, freezer, timedelta(hours=167))
    assert sync_time.await_count == 1
    await advance(hass, freezer, timedelta(hours=1, seconds=1))
    assert sync_time.await_count == 2


async def test_next_sync_follows_schedule(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, sync_time: AsyncMock
) -> None:
    await setup(hass)
    next_sync = entity_id(hass, "sensor", "next_sync")

    def scheduled() -> str:
        return hass.states.get(next_sync).state

    def from_now(delta: timedelta) -> str:
        # Timestamp sensors drop microseconds.
        return (dt_util.utcnow() + delta).replace(microsecond=0).isoformat()

    assert scheduled() == from_now(timedelta(seconds=30))

    await advance(hass, freezer, timedelta(seconds=31))
    assert scheduled() == from_now(timedelta(hours=168))

    # A failure shows the retry time.
    sync_time.side_effect = TimeoutError("out of range")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": entity_id(hass, "button", "sync_time")},
            blocking=True,
        )
    assert scheduled() == from_now(timedelta(minutes=15))

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": entity_id(hass, "switch", "auto_sync")},
        blocking=True,
    )
    assert scheduled() == STATE_UNKNOWN


async def test_button_syncs_and_reports_failures(
    hass: HomeAssistant, sync_time: AsyncMock
) -> None:
    await setup(hass)
    button = entity_id(hass, "button", "sync_time")

    await hass.services.async_call(
        "button", "press", {"entity_id": button}, blocking=True
    )
    assert sync_time.await_count == 1

    sync_time.side_effect = TimeoutError("proxy busy")
    with pytest.raises(HomeAssistantError, match="proxy busy"):
        await hass.services.async_call(
            "button", "press", {"entity_id": button}, blocking=True
        )
    # A failure keeps the last known values.
    assert hass.states.get(entity_id(hass, "sensor", "drift")).state == "3"


async def test_failures_retry_quietly(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, sync_time: AsyncMock
) -> None:
    await setup(hass)
    sync_time.side_effect = TimeoutError("out of range")
    last_sync = entity_id(hass, "sensor", "last_sync")

    await advance(hass, freezer, timedelta(seconds=31))
    # Backoff: 15 min, 30 min, 1 h, 2 h.
    for attempt, minutes in ((2, 15), (3, 30), (4, 60), (5, 120)):
        await advance(hass, freezer, timedelta(minutes=minutes - 1))
        assert sync_time.await_count == attempt - 1
        await advance(hass, freezer, timedelta(minutes=1, seconds=1))
        assert sync_time.await_count == attempt
    assert ir.async_get(hass).issues == {}
    assert hass.states.get(last_sync).state == STATE_UNKNOWN

    sync_time.side_effect = None
    await advance(hass, freezer, timedelta(hours=4, seconds=1))
    assert hass.states.get(last_sync).state != STATE_UNKNOWN
    # Back on the normal interval.
    await advance(hass, freezer, timedelta(hours=167))
    assert sync_time.await_count == 6


async def test_turning_auto_off_stops_schedule(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    sync_time: AsyncMock,
    hass_storage: dict[str, Any],
) -> None:
    entry = await setup(hass)
    switch = entity_id(hass, "switch", "auto_sync")

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": switch}, blocking=True
    )
    assert hass.states.get(switch).state == STATE_OFF
    assert hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]["auto_enabled"] is False

    await advance(hass, freezer, timedelta(days=30))
    sync_time.assert_not_awaited()


async def test_restart_continues_from_last_sync(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    sync_time: AsyncMock,
    hass_storage: dict[str, Any],
) -> None:
    entry = config_entry()
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {
            "auto_enabled": True,
            "interval_hours": 24,
            "last_sync": (dt_util.utcnow() - timedelta(hours=20)).isoformat(),
            "drift_seconds": -2,
        },
    }
    await setup(hass, entry)
    assert hass.states.get(entity_id(hass, "sensor", "drift")).state == "-2"

    await advance(hass, freezer, timedelta(hours=3, minutes=59))
    sync_time.assert_not_awaited()
    await advance(hass, freezer, timedelta(minutes=2))
    sync_time.assert_awaited_once()


# US/Pacific, the time zone of the test instance, leaves DST on 2026-11-01 at
# 02:00 PDT.
PDT = -7 * 3600
PST = -8 * 3600
FALL_BACK = dt_util.parse_datetime("2026-11-01T09:00:00+00:00")


def stored_state(entry: MockConfigEntry, **data: Any) -> dict[str, Any]:
    return {"version": 1, "key": f"{DOMAIN}.{entry.entry_id}", "data": data}


async def test_dst_change_syncs_at_once_and_keeps_true_drift(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    sync_time: AsyncMock,
    hass_storage: dict[str, Any],
) -> None:
    freezer.move_to(FALL_BACK - timedelta(hours=1))
    entry = config_entry()
    key = f"{DOMAIN}.{entry.entry_id}"
    hass_storage[key] = stored_state(
        entry,
        interval_hours=168,
        last_sync=(FALL_BACK - timedelta(days=1)).isoformat(),
        drift_seconds=0,
        utc_offset=PDT,
    )
    await setup(hass, entry)
    assert hass.states.get(entity_id(hass, "sensor", "next_sync")).state == (
        FALL_BACK.isoformat()
    )

    await advance(hass, freezer, timedelta(minutes=59))
    sync_time.assert_not_awaited()
    # Still on PDT, the device reads an hour ahead of PST.
    sync_time.return_value = replace(OK, drift_seconds=3600 + 3)
    await advance(hass, freezer, timedelta(minutes=1, seconds=1))

    sync_time.assert_awaited_once()
    assert hass.states.get(entity_id(hass, "sensor", "drift")).state == "3"
    assert hass_storage[key]["data"]["utc_offset"] == PST


async def test_overdue_offset_change_syncs_after_startup(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    sync_time: AsyncMock,
    hass_storage: dict[str, Any],
) -> None:
    """Home Assistant was down across the change."""
    freezer.move_to(FALL_BACK + timedelta(hours=5))
    entry = config_entry()
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = stored_state(
        entry,
        interval_hours=168,
        last_sync=(FALL_BACK - timedelta(days=1)).isoformat(),
        utc_offset=PDT,
    )
    await setup(hass, entry)

    await advance(hass, freezer, timedelta(seconds=31))
    sync_time.assert_awaited_once()


async def test_time_zone_change_syncs(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    sync_time: AsyncMock,
    hass_storage: dict[str, Any],
) -> None:
    entry = config_entry()
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = stored_state(
        entry,
        interval_hours=168,
        last_sync=(dt_util.utcnow() - timedelta(hours=1)).isoformat(),
        utc_offset=int(dt_util.now().utcoffset().total_seconds()),
    )
    await setup(hass, entry)
    await advance(hass, freezer, timedelta(minutes=5))
    sync_time.assert_not_awaited()

    await hass.config.async_update(time_zone="Asia/Taipei")
    await advance(hass, freezer, timedelta(seconds=31))
    sync_time.assert_awaited_once()


async def test_unload_and_remove(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    sync_time: AsyncMock,
    hass_storage: dict[str, Any],
) -> None:
    entry = await setup(hass)
    await advance(hass, freezer, timedelta(seconds=31))
    key = f"{DOMAIN}.{entry.entry_id}"
    assert key in hass_storage

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    await advance(hass, freezer, timedelta(days=30))
    assert sync_time.await_count == 1

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage


async def test_own_device_borrows_sensor_name_and_area(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, sync_time: AsyncMock
) -> None:
    area = ar.async_get(hass).async_create("臥室")
    add_bthome_device(hass, area_id=area.id)
    entry = await setup(hass)

    devices = dr.async_get(hass)
    own = dr.async_entries_for_config_entry(devices, entry.entry_id)
    assert len(own) == 1
    assert own[0].name == "牆上溫濕度感應器"
    assert own[0].area_id == area.id
    assert own[0].model is None

    await advance(hass, freezer, timedelta(seconds=31))
    device = devices.async_get(own[0].id)
    assert (device.model, device.sw_version) == ("MJWSD05MMC", "5.9")


async def test_not_pvvx_twice_raises_issue_and_stops_auto_sync(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, sync_time: AsyncMock
) -> None:
    entry = await setup(hass)
    sync_time.side_effect = NotPvvxDeviceError("unexpected firmware: 'atc1441'")
    issues = ir.async_get(hass)
    issue_id = f"not_pvvx_{entry.entry_id}"

    # Once could be a stale service cache: retry.
    await advance(hass, freezer, timedelta(seconds=31))
    assert issues.async_get_issue(DOMAIN, issue_id) is None

    await advance(hass, freezer, timedelta(minutes=15, seconds=1))
    issue = issues.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_key == "not_pvvx"

    await advance(hass, freezer, timedelta(days=30))
    assert sync_time.await_count == 2

    # Removing the entry takes its issue along.
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, issue_id) is None


async def test_button_during_running_sync_joins_it(hass: HomeAssistant) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_sync(self: PvvxClient) -> SyncResult:
        started.set()
        await release.wait()
        return OK

    with patch.object(
        PvvxClient, "sync_time", autospec=True, side_effect=slow_sync
    ) as mock:
        await setup(hass)
        coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
        first = hass.async_create_task(coordinator.async_sync_now())
        await started.wait()
        press = hass.async_create_task(
            hass.services.async_call(
                "button",
                "press",
                {"entity_id": entity_id(hass, "button", "sync_time")},
                blocking=True,
            )
        )
        await asyncio.sleep(0)
        release.set()
        await first
        await press

    assert mock.await_count == 1


async def test_interval_defaults_by_clock_type_and_can_be_changed(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, sync_time: AsyncMock
) -> None:
    await setup(hass)
    interval = entity_id(hass, "number", "interval")
    # Clock type unknown before the first sync.
    assert hass.states.get(interval).state == "24"

    await advance(hass, freezer, timedelta(seconds=31))
    assert hass.states.get(interval).state == "168"

    await hass.services.async_call(
        "number", "set_value", {"entity_id": interval, "value": 2}, blocking=True
    )
    assert hass.states.get(interval).state == "2"
    await advance(hass, freezer, timedelta(hours=2, seconds=1))
    assert sync_time.await_count == 2


async def test_button_needs_device_in_range(
    hass: HomeAssistant, sync_time: AsyncMock
) -> None:
    with patch.object(
        coordinator_module.bluetooth, "async_address_present", return_value=False
    ):
        entry = await setup(hass)
    button = entity_id(hass, "button", "sync_time")
    assert hass.states.get(button).state == STATE_UNAVAILABLE
    # Settings and last values stay usable.
    assert hass.states.get(entity_id(hass, "switch", "auto_sync")).state == STATE_ON

    coordinator = entry.runtime_data
    coordinator._on_advertisement(None, None)
    await hass.async_block_till_done()
    assert hass.states.get(button).state != STATE_UNAVAILABLE

    coordinator._on_unavailable(None)
    await hass.async_block_till_done()
    assert hass.states.get(button).state == STATE_UNAVAILABLE


async def test_unload_during_sync_leaves_no_timer(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def slow_sync(self: PvvxClient) -> SyncResult:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return OK

    with patch.object(PvvxClient, "sync_time", autospec=True, side_effect=slow_sync):
        entry = await setup(hass)
        freezer.tick(timedelta(seconds=31))
        async_fire_time_changed(hass)
        await started.wait()

        assert await hass.config_entries.async_unload(entry.entry_id)
        release.set()
        await hass.async_block_till_done(wait_background_tasks=True)

        await advance(hass, freezer, timedelta(days=30))
    assert calls == 1


async def test_timer_during_button_sync_does_not_sync_twice(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def slow_sync(self: PvvxClient) -> SyncResult:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return OK

    with patch.object(PvvxClient, "sync_time", autospec=True, side_effect=slow_sync):
        entry = await setup(hass)
        press = hass.async_create_task(entry.runtime_data.async_sync_now())
        await started.wait()
        freezer.tick(timedelta(seconds=31))
        async_fire_time_changed(hass)
        # Let the timer run; waiting for all tasks would wait for the press.
        for _ in range(5):
            await asyncio.sleep(0)
        release.set()
        await press
        await hass.async_block_till_done(wait_background_tasks=True)
    assert calls == 1


async def test_turning_auto_back_on_resumes_schedule(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, sync_time: AsyncMock
) -> None:
    await setup(hass)
    switch = entity_id(hass, "switch", "auto_sync")
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": switch}, blocking=True
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": switch}, blocking=True
    )
    assert hass.states.get(switch).state == STATE_ON
    await advance(hass, freezer, timedelta(seconds=31))
    sync_time.assert_awaited_once()


async def test_local_clock_uses_home_assistant_time_zone(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Asia/Taipei")
    assert local_clock() - time.time() == pytest.approx(8 * 3600, abs=1)


async def test_connect_fails_when_no_adapter_sees_the_device(
    hass: HomeAssistant,
) -> None:
    connect = make_connect(hass, ADDRESS, "clock")
    with pytest.raises(PvvxError, match="not in range"):
        await connect()


async def test_retry_backoff_never_exceeds_interval(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, sync_time: AsyncMock
) -> None:
    await setup(hass)
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": entity_id(hass, "number", "interval"), "value": 1},
        blocking=True,
    )
    sync_time.side_effect = TimeoutError("out of range")
    await advance(hass, freezer, timedelta(seconds=31))
    # 15 min, 30 min, then capped at the 1 h interval.
    for attempt, minutes in ((2, 15), (3, 30), (4, 60), (5, 60)):
        await advance(hass, freezer, timedelta(minutes=minutes, seconds=1))
        assert sync_time.await_count == attempt
