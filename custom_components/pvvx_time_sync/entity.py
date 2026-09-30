"""Base entity for pvvx Time Sync."""

from __future__ import annotations

from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar, device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PvvxCoordinator

# Integrations whose device for the same address names ours, most preferred
# first. Any other integration's device is the next fallback.
PREFERRED_SENSOR_DOMAINS = ("bthome", "xiaomi_ble")


@callback
def async_sensor_device(hass: HomeAssistant, address: str) -> dr.DeviceEntry | None:
    """Find another integration's device for this Bluetooth address."""
    registry = dr.async_get(hass)
    candidates: list[tuple[int, dr.DeviceEntry]] = []
    for device in registry.async_get_devices(
        connections={(CONNECTION_BLUETOOTH, address)}
    ):
        entry = hass.config_entries.async_get_entry(device.config_entry_id)
        if entry is None or entry.domain == DOMAIN:
            continue
        rank = (
            PREFERRED_SENSOR_DOMAINS.index(entry.domain)
            if entry.domain in PREFERRED_SENSOR_DOMAINS
            else len(PREFERRED_SENSOR_DOMAINS)
        )
        candidates.append((rank, device))
    return min(candidates, key=lambda c: c[0])[1] if candidates else None


class PvvxEntity(CoordinatorEntity[PvvxCoordinator]):
    """Entity of the time sync device owned by this config entry.

    Since HA 2026.8 each config entry owns its devices, so this is a device of
    its own next to the BTHome one; it borrows that device's name and area.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: PvvxCoordinator, key: str) -> None:
        """Attach the ``key`` entity to this entry's time sync device."""
        super().__init__(coordinator)
        hass = coordinator.hass
        entry = coordinator.config_entry
        address = entry.data[CONF_ADDRESS]
        self._attr_translation_key = key
        self._attr_unique_id = f"{address}_{key}"

        sensor = async_sensor_device(hass, address)
        area = (
            ar.async_get(hass).async_get_area(sensor.area_id)
            if sensor and sensor.area_id
            else None
        )
        state = coordinator.data
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, address)},
            name=(sensor.name_by_user or sensor.name) if sensor else entry.title,
            model=state.model,
            sw_version=state.firmware,
            suggested_area=area.name if area else None,
        )

    @property
    def available(self) -> bool:
        """A failed sync does not make the last known values unknown."""
        return True
