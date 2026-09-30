"""Tests for the pvvx Time Sync config flow."""

from unittest.mock import patch

import pytest

from custom_components.pvvx_time_sync.client import PvvxClient
from custom_components.pvvx_time_sync.const import DOMAIN
from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .common import ADDRESS, add_bthome_device, config_entry, service_info

pytestmark = pytest.mark.usefixtures("enable_bluetooth")


def patch_discovered(*infos):
    return patch(
        "custom_components.pvvx_time_sync.config_flow.async_discovered_service_info",
        return_value=list(infos),
    )


def patch_setup():
    return patch(
        "custom_components.pvvx_time_sync.async_setup_entry", return_value=True
    )


def forbid_connecting():
    """Adding a device must never talk to it."""
    return patch.object(PvvxClient, "sync_time", side_effect=AssertionError)


async def test_bluetooth_discovery_creates_entry_without_connecting(
    hass: HomeAssistant,
) -> None:
    add_bthome_device(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"
    assert result["description_placeholders"] == {"name": "牆上溫濕度感應器"}

    with forbid_connecting(), patch_setup():
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "牆上溫濕度感應器"
    assert result["data"] == {CONF_ADDRESS: ADDRESS}
    assert result["result"].unique_id == ADDRESS


async def test_title_falls_back_to_advertised_name(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )
    with patch_setup():
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["title"] == "BTH_123456"


async def test_bluetooth_discovery_aborts_when_configured(hass: HomeAssistant) -> None:
    config_entry().add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_lists_renamed_bthome_devices(hass: HomeAssistant) -> None:
    renamed = service_info(
        "Bedroom clock", service_data={"0000fcd2-0000-1000-8000-00805f9b34fb": b"\x40"}
    )
    other = service_info("Some speaker", "11:22:33:44:55:66")
    not_connectable = service_info("BTH_000000", "11:22:33:44:55:77", connectable=False)
    with patch_discovered(renamed, other, not_connectable):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    assert result["type"] is FlowResultType.FORM
    choices = result["data_schema"].schema[CONF_ADDRESS].container
    assert list(choices) == [ADDRESS]

    with forbid_connecting(), patch_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bedroom clock"


async def test_user_flow_matches_default_pvvx_names(hass: HomeAssistant) -> None:
    with patch_discovered(service_info("ATC_123456", "11:22:33:44:55:66")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    assert list(result["data_schema"].schema[CONF_ADDRESS].container) == [
        "11:22:33:44:55:66"
    ]


async def test_user_flow_aborts_when_configured_meanwhile(
    hass: HomeAssistant,
) -> None:
    with patch_discovered(service_info()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    config_entry().add_to_hass(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_aborts_without_candidates(hass: HomeAssistant) -> None:
    with patch_discovered(service_info("Some speaker")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"
