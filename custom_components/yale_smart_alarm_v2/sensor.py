"""Sensors for Yale Alarm."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import COORDINATOR, DOMAIN
from .coordinator import YaleDataUpdateCoordinator
from .entity import YaleEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Yale sensor entry."""

    coordinator: YaleDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        COORDINATOR
    ]
    sensors: list[YaleTemperatureSensor] = []
    for data in coordinator.data["temperature_sensors"]:
        sensors.append(YaleTemperatureSensor(coordinator, data))

    async_add_entities(sensors)


class YaleTemperatureSensor(YaleEntity, SensorEntity):
    """Representation of a Yale Temperature sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def state(self) -> float:
        """Return the temperature as a float."""
        return float(self.coordinator.data["temperature_map"][self._attr_unique_id])
