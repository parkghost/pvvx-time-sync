"""Config flow for pvvx Time Sync.

Adding a device never connects to it: Bluetooth connections through proxies
are slow and flaky, so the firmware is verified during the first sync instead.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import (
    DOMAIN,
    PVVX_NAME_PREFIXES,
    PVVX_SERVICE_DATA_UUIDS,
)
from .entity import async_sensor_device


def is_candidate(info: BluetoothServiceInfoBleak) -> bool:
    """Whether a device may run pvvx firmware; the first sync makes sure."""
    if not info.connectable:
        return False
    if info.name.startswith(PVVX_NAME_PREFIXES):
        return True
    return any(uuid in info.service_data for uuid in PVVX_SERVICE_DATA_UUIDS)


class PvvxTimeSyncConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add pvvx devices found in Bluetooth advertisements."""

    VERSION = 1

    def __init__(self) -> None:
        """Start a flow with no device picked yet."""
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._candidates: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a device found by its advertised name."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": self._title(discovery_info)}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add the discovered device once the user agrees."""
        assert self._discovery is not None
        if user_input is not None:
            return self._create(self._discovery)
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._title(self._discovery)},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick a nearby device, including renamed ones."""
        if user_input is not None:
            info = self._candidates[user_input[CONF_ADDRESS]]
            await self.async_set_unique_id(info.address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self._create(info)

        configured = self._async_current_ids(include_ignore=False)
        self._candidates = {
            info.address: info
            for info in async_discovered_service_info(self.hass, connectable=True)
            if info.address not in configured and is_candidate(info)
        }
        if not self._candidates:
            return self.async_abort(reason="no_devices_found")

        labels = {
            address: f"{self._title(info)} ({info.name}, {address})"
            for address, info in self._candidates.items()
        }
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        dict(sorted(labels.items(), key=lambda item: item[1]))
                    )
                }
            ),
        )

    def _title(self, info: BluetoothServiceInfoBleak) -> str:
        """Name of the sensor device for this address, else the advertised name."""
        if sensor := async_sensor_device(self.hass, info.address):
            return sensor.name_by_user or sensor.name or info.name
        return info.name

    def _create(self, info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._title(info), data={CONF_ADDRESS: info.address}
        )
