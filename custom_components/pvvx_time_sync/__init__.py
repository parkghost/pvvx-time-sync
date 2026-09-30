"""pvvx Time Sync: sets the clock of pvvx-firmware BLE devices."""

from __future__ import annotations

import time

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .client import ConnectFn, GattClient, PvvxClient
from .coordinator import PvvxConfigEntry, PvvxCoordinator, remove_store
from .protocol import PvvxError

PLATFORMS = [Platform.BUTTON, Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]


def local_clock() -> float:
    """Return the local wall-clock time as epoch seconds, in HA's time zone."""
    offset = dt_util.now().utcoffset()
    return time.time() + (offset.total_seconds() if offset else 0)


def make_connect(hass: HomeAssistant, address: str, name: str) -> ConnectFn:
    """Build a connector that picks the best connectable adapter or proxy each time."""

    async def connect() -> GattClient:
        ble_device = bluetooth.async_ble_device_from_address(
            hass, address, connectable=True
        )
        if ble_device is None:
            raise PvvxError(f"{address} is not in range of a connectable adapter")
        return await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            name,
            max_attempts=3,
            # Lets retries pick whichever adapter or proxy sees the device now.
            ble_device_callback=lambda: (
                bluetooth.async_ble_device_from_address(hass, address, connectable=True)
                or ble_device
            ),
        )

    return connect


async def async_setup_entry(hass: HomeAssistant, entry: PvvxConfigEntry) -> bool:
    """Set up a pvvx device from a config entry."""
    client = PvvxClient(
        make_connect(hass, entry.data[CONF_ADDRESS], entry.title),
        local_clock,
        name=entry.title,
    )
    coordinator = PvvxCoordinator(hass, entry, client)
    await coordinator.async_load()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PvvxConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: PvvxConfigEntry) -> None:
    """Delete persisted sync state when the entry is removed."""
    await remove_store(hass, entry.entry_id)
