"""Test helpers."""

from __future__ import annotations

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pvvx_time_sync.const import DOMAIN
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

ADDRESS = "A4:C1:38:12:34:56"


def service_info(
    name: str = "BTH_123456",
    address: str = ADDRESS,
    *,
    connectable: bool = True,
    service_data: dict[str, bytes] | None = None,
) -> BluetoothServiceInfoBleak:
    service_data = service_data or {}
    return BluetoothServiceInfoBleak(
        name=name,
        address=address,
        rssi=-60,
        manufacturer_data={},
        service_data=service_data,
        service_uuids=[],
        source="local",
        device=BLEDevice(address, name, None),
        advertisement=AdvertisementData(
            local_name=name,
            manufacturer_data={},
            service_data=service_data,
            service_uuids=[],
            tx_power=None,
            rssi=-60,
            platform_data=(),
        ),
        connectable=connectable,
        time=0,
        tx_power=None,
    )


def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        title="牆上溫濕度感應器",
        data={CONF_ADDRESS: ADDRESS},
    )


def add_bthome_device(
    hass: HomeAssistant, name: str = "牆上溫濕度感應器", area_id: str | None = None
) -> dr.DeviceEntry:
    """Register the sensor device the BTHome integration would create."""
    bthome = MockConfigEntry(domain="bthome", unique_id=ADDRESS)
    bthome.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=bthome.entry_id,
        identifiers={("bluetooth", ADDRESS)},
        connections={(dr.CONNECTION_BLUETOOTH, ADDRESS)},
        name=name,
    )
    if area_id:
        device = dr.async_get(hass).async_update_device(device.id, area_id=area_id)
    return device
