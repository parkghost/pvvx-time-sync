"""Sync scheduling and state for one pvvx device."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
import logging
from typing import Any, override

from bleak.exc import BleakError

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import NotPvvxDeviceError, PvvxClient
from .const import (
    DOMAIN,
    NOT_PVVX_CONFIRMATIONS,
    RETRY_DELAY,
    default_interval_hours,
)
from .protocol import PvvxError

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
# Gives Bluetooth proxies time to reconnect after a Home Assistant restart.
STARTUP_DELAY = timedelta(seconds=30)
# Devices that are due at startup are spread over this many seconds by address,
# so they do not all compete for the proxies' few connection slots at once.
STARTUP_SPREAD_SECONDS = 90

type PvvxConfigEntry = ConfigEntry[PvvxCoordinator]


def _store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")


async def remove_store(hass: HomeAssistant, entry_id: str) -> None:
    """Delete the persisted state of a removed entry."""
    await _store(hass, entry_id).async_remove()


def issue_id(entry_id: str) -> str:
    """Repair issue id of an entry."""
    return f"not_pvvx_{entry_id}"


@dataclass(frozen=True, slots=True)
class SyncState:
    """Persisted sync state of a device."""

    auto_enabled: bool = True
    # None follows the clock type default (default_interval_hours).
    interval_hours: int | None = None
    last_sync: datetime | None = None
    drift_seconds: int | None = None
    # Reported by the device during a sync; unknown until the first one.
    model: str | None = None
    firmware: str | None = None
    hardware_clock: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the Store."""
        data = asdict(self)
        data["last_sync"] = self.last_sync.isoformat() if self.last_sync else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SyncState:
        """Deserialize from the Store, tolerating keys of older versions."""
        last_sync = data.get("last_sync")
        return cls(
            auto_enabled=data.get("auto_enabled", True),
            interval_hours=data.get("interval_hours"),
            last_sync=dt_util.parse_datetime(last_sync) if last_sync else None,
            drift_seconds=data.get("drift_seconds"),
            model=data.get("model"),
            firmware=data.get("firmware"),
            hardware_clock=data.get("hardware_clock"),
        )


class PvvxCoordinator(DataUpdateCoordinator[SyncState]):
    """Runs time syncs on demand and on an interval.

    ``update_interval`` stays None: the next automatic run is scheduled from
    the last successful sync, which is persisted across restarts.
    """

    config_entry: PvvxConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: PvvxConfigEntry, client: PvvxClient
    ) -> None:
        """Sync the device of ``entry`` through ``client``."""
        super().__init__(hass, _LOGGER, config_entry=entry, name=entry.title)
        self._client = client
        self._address: str = entry.data[CONF_ADDRESS]
        self._store = _store(hass, entry.entry_id)
        self._lock = asyncio.Lock()
        self._cancel_timer: CALLBACK_TYPE | None = None
        self._failures = 0
        self._not_pvvx_strikes = 0
        self._stopped = False
        self.present = False
        self.data = SyncState()

    @property
    def interval_hours(self) -> int:
        """Configured auto sync interval, or the default for the clock type."""
        if self.data.interval_hours is not None:
            return self.data.interval_hours
        return default_interval_hours(hardware_clock=self.data.hardware_clock)

    @property
    def interval(self) -> timedelta:
        """Auto sync interval."""
        return timedelta(hours=self.interval_hours)

    @property
    def gave_up(self) -> bool:
        """The device answered repeatedly without pvvx firmware."""
        return self._not_pvvx_strikes >= NOT_PVVX_CONFIRMATIONS

    async def async_load(self) -> None:
        """Restore persisted state, track presence and arm the auto sync timer."""
        if stored := await self._store.async_load():
            self.data = SyncState.from_dict(stored)
        self._track_presence()
        self._reschedule()

    @override
    async def async_shutdown(self) -> None:
        """Stop scheduling; a sync still in flight must not re-arm the timer."""
        self._stopped = True
        self._cancel()
        ir.async_delete_issue(self.hass, DOMAIN, issue_id(self.config_entry.entry_id))
        await super().async_shutdown()

    async def async_set_auto(self, *, enabled: bool) -> None:
        """Turn automatic syncing on or off."""
        await self._commit(replace(self.data, auto_enabled=enabled))
        self._reschedule()

    async def async_set_interval_hours(self, hours: int) -> None:
        """Change the auto sync interval; the next run moves accordingly."""
        await self._commit(replace(self.data, interval_hours=hours))
        self._reschedule()

    async def async_sync_now(self) -> None:
        """Sync immediately; raise so callers such as automations see failures.

        A press during a running sync waits for it rather than connecting again.
        """
        if self._lock.locked():
            _LOGGER.debug("%s: sync requested while one runs; waiting", self.name)
            async with self._lock:
                pass
        else:
            _LOGGER.debug("%s: sync requested", self.name)
            await self._run()
        if not self.last_update_success:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="sync_failed",
                translation_placeholders={
                    "name": self.config_entry.title,
                    "error": str(self.last_exception),
                },
            )

    @override
    async def _async_update_data(self) -> SyncState:
        try:
            result = await self._client.sync_time()
        except NotPvvxDeviceError as err:
            self._not_pvvx_strikes += 1
            raise UpdateFailed(str(err)) from err
        except (PvvxError, BleakError, TimeoutError) as err:
            raise UpdateFailed(f"{type(err).__name__}: {err}") from err
        _LOGGER.debug(
            "%s: synced, drift before sync %+ds", self.name, result.drift_seconds
        )
        details = result.details
        state = replace(
            self.data,
            last_sync=dt_util.utcnow(),
            drift_seconds=result.drift_seconds,
            model=details.model,
            firmware=details.firmware,
            hardware_clock=details.has_hardware_clock,
        )
        await self._store.async_save(state.to_dict())
        self._update_device(details.model, details.firmware)
        return state

    def _update_device(self, model: str, firmware: str) -> None:
        registry = dr.async_get(self.hass)
        if device := registry.async_get_device_by_connection(
            (dr.CONNECTION_BLUETOOTH, self._address), self.config_entry.entry_id
        ):
            registry.async_update_device(device.id, model=model, sw_version=firmware)

    async def _run(self) -> None:
        async with self._lock:
            await self.async_refresh()
        if self._stopped:
            return
        if self.last_update_success:
            self._failures = 0
            self._not_pvvx_strikes = 0
            ir.async_delete_issue(
                self.hass, DOMAIN, issue_id(self.config_entry.entry_id)
            )
        elif self.gave_up:
            # Retrying cannot help; wait for the user to remove the entry.
            _LOGGER.warning(
                "%s: no pvvx firmware found %d times in a row; auto sync stopped",
                self.name,
                self._not_pvvx_strikes,
            )
            self._create_issue()
        else:
            # Usually transient (out of range, busy proxy): retry quietly.
            self._failures += 1
        self._reschedule()

    async def _commit(self, state: SyncState) -> None:
        # Not async_set_updated_data: that would also mark a failing sync as
        # successful and reset the unavailability logging.
        await self._store.async_save(state.to_dict())
        self.data = state
        self.async_update_listeners()

    @callback
    def _cancel(self) -> None:
        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None

    @callback
    def _reschedule(self) -> None:
        self._cancel()
        if self._stopped or not self.data.auto_enabled or self.gave_up:
            _LOGGER.debug("%s: no auto sync scheduled", self.name)
            return
        delay, reason = self._next_delay()
        _LOGGER.debug("%s: next auto sync in %s (%s)", self.name, delay, reason)
        self._cancel_timer = async_call_later(self.hass, delay, self._on_timer)

    def _next_delay(self) -> tuple[timedelta, str]:
        if self._failures:
            backoff = RETRY_DELAY * 2 ** min(self._failures - 1, 16)
            return min(backoff, self.interval), f"retry {self._failures}"
        startup = STARTUP_DELAY + timedelta(
            seconds=int(self._address.replace(":", ""), 16)
            % (STARTUP_SPREAD_SECONDS + 1)
        )
        if self.data.last_sync is None:
            return startup, "first sync"
        due = self.data.last_sync + self.interval - dt_util.utcnow()
        if due < startup:
            return startup, "overdue"
        return due, f"every {self.interval_hours} h"

    @callback
    def _on_timer(self, _now: datetime) -> None:
        self._cancel_timer = None
        # A sync already in progress reschedules when it finishes.
        if self._lock.locked() or self.hass.is_stopping:
            _LOGGER.debug("%s: auto sync skipped; sync running or stopping", self.name)
            return
        _LOGGER.debug("%s: auto sync starting", self.name)
        self.config_entry.async_create_background_task(
            self.hass, self._run(), f"{DOMAIN} auto sync {self.name}"
        )

    @callback
    def _track_presence(self) -> None:
        """Follow whether a connectable adapter or proxy currently sees the device."""
        self.present = bluetooth.async_address_present(
            self.hass, self._address, connectable=True
        )
        entry = self.config_entry
        entry.async_on_unload(
            bluetooth.async_register_callback(
                self.hass,
                self._on_advertisement,
                bluetooth.BluetoothCallbackMatcher(
                    address=self._address, connectable=True
                ),
                bluetooth.BluetoothScanningMode.PASSIVE,
            )
        )
        entry.async_on_unload(
            bluetooth.async_track_unavailable(
                self.hass, self._on_unavailable, self._address, connectable=True
            )
        )

    @callback
    def _on_advertisement(
        self,
        _info: bluetooth.BluetoothServiceInfoBleak,
        _change: bluetooth.BluetoothChange,
    ) -> None:
        if not self.present:
            _LOGGER.debug("%s: seen by a connectable adapter", self.name)
            self.present = True
            self.async_update_listeners()

    @callback
    def _on_unavailable(self, _info: bluetooth.BluetoothServiceInfoBleak) -> None:
        _LOGGER.debug("%s: no longer seen by a connectable adapter", self.name)
        self.present = False
        self.async_update_listeners()

    def _create_issue(self) -> None:
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id(self.config_entry.entry_id),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="not_pvvx",
            translation_placeholders={
                "name": self.config_entry.title,
                "error": str(self.last_exception),
            },
        )
