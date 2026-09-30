"""Auto sync switch for pvvx Time Sync."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import PvvxConfigEntry
from .entity import PvvxEntity

# Actions are serialized by the coordinator's own lock.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PvvxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the auto sync switch."""
    async_add_entities([PvvxAutoSyncSwitch(entry.runtime_data, "auto_sync")])


class PvvxAutoSyncSwitch(PvvxEntity, SwitchEntity):
    """Enables the built-in interval schedule."""

    _attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool:
        """Return whether auto sync is on."""
        return self.coordinator.data.auto_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn auto sync on."""
        await self.coordinator.async_set_auto(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn auto sync off."""
        await self.coordinator.async_set_auto(enabled=False)
