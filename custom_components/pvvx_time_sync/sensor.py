"""Sync status sensors for pvvx Time Sync."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import PvvxConfigEntry, PvvxCoordinator, SyncState
from .entity import PvvxEntity


@dataclass(frozen=True, kw_only=True)
class PvvxSensorDescription(SensorEntityDescription):
    """Describes a sensor derived from the sync state."""

    value_fn: Callable[[SyncState], datetime | int | None]


SENSORS = (
    PvvxSensorDescription(
        key="last_sync",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.last_sync,
    ),
    PvvxSensorDescription(
        key="drift",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.drift_seconds,
    ),
)


# Coordinator based: entities never update themselves.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PvvxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sync status sensors."""
    async_add_entities(
        PvvxSensor(entry.runtime_data, description) for description in SENSORS
    )


class PvvxSensor(PvvxEntity, SensorEntity):
    """Reports a field of the last successful sync."""

    entity_description: PvvxSensorDescription

    def __init__(
        self, coordinator: PvvxCoordinator, description: PvvxSensorDescription
    ) -> None:
        """Describe the entity by ``description``."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> datetime | int | None:
        """Return the field from the sync state."""
        return self.entity_description.value_fn(self.coordinator.data)
