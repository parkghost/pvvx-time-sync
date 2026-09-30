"""Sync-now button for pvvx Time Sync."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    """Set up the sync button."""
    async_add_entities([PvvxSyncButton(entry.runtime_data, "sync_time")])


class PvvxSyncButton(PvvxEntity, ButtonEntity):
    """Syncs the clock now; failures surface to the caller."""

    @property
    def available(self) -> bool:
        """Pressable only while a connectable adapter or proxy sees the device."""
        return self.coordinator.present

    async def async_press(self) -> None:
        """Sync the clock now."""
        await self.coordinator.async_sync_now()
