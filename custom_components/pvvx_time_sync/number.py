"""Sync settings as number entities for pvvx Time Sync."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import MAX_INTERVAL_HOURS
from .coordinator import PvvxConfigEntry, PvvxCoordinator
from .entity import PvvxEntity


@dataclass(frozen=True, kw_only=True)
class PvvxNumberDescription(NumberEntityDescription):
    """Describes a sync setting."""

    value_fn: Callable[[PvvxCoordinator], int]
    set_fn: Callable[[PvvxCoordinator, int], Awaitable[None]]


NUMBERS = (
    PvvxNumberDescription(
        key="interval",
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        native_min_value=1,
        native_max_value=MAX_INTERVAL_HOURS,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda coordinator: coordinator.interval_hours,
        set_fn=lambda coordinator, value: coordinator.async_set_interval_hours(value),
    ),
)


# Actions are serialized by the coordinator's own lock.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PvvxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sync settings."""
    async_add_entities(
        PvvxNumber(entry.runtime_data, description) for description in NUMBERS
    )


class PvvxNumber(PvvxEntity, NumberEntity):
    """A sync setting stored with the sync state."""

    entity_description: PvvxNumberDescription

    def __init__(
        self, coordinator: PvvxCoordinator, description: PvvxNumberDescription
    ) -> None:
        """Describe the entity by ``description``."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int:
        """Return the current setting."""
        return self.entity_description.value_fn(self.coordinator)

    async def async_set_native_value(self, value: float) -> None:
        """Store a new setting."""
        await self.entity_description.set_fn(self.coordinator, int(value))
