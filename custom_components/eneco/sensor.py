"""Read-only Eneco heat and payment sensors."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import EnecoConfigEntry, EnecoCoordinator
from .data import latest_day, latest_value, period_total


@dataclass(frozen=True, kw_only=True)
class EnecoSensorDescription(SensorEntityDescription):
    """Describe the value reader."""

    value_fn: Callable[[dict[str, Any]], Any]


ENERGY = {
    "native_unit_of_measurement": UnitOfEnergy.GIGA_JOULE,
    "device_class": SensorDeviceClass.ENERGY,
    "suggested_display_precision": 3,
}
MONEY = {
    "native_unit_of_measurement": "EUR",
    "device_class": SensorDeviceClass.MONETARY,
    "suggested_display_precision": 2,
}
SENSORS = (
    EnecoSensorDescription(
        key="heat_latest_day",
        translation_key="heat_latest_day",
        value_fn=lambda d: latest_value(d, "usage"),
        **ENERGY,
    ),
    EnecoSensorDescription(
        key="heat_this_month",
        translation_key="heat_this_month",
        value_fn=lambda d: period_total(d, dt_util.now().date(), "usage"),
        **ENERGY,
    ),
    EnecoSensorDescription(
        key="heat_previous_month",
        translation_key="heat_previous_month",
        value_fn=lambda d: period_total(d, dt_util.now().date(), "usage", True),
        **ENERGY,
    ),
    EnecoSensorDescription(
        key="cost_latest_day",
        translation_key="cost_latest_day",
        value_fn=lambda d: latest_value(d, "cost"),
        **MONEY,
    ),
    EnecoSensorDescription(
        key="cost_this_month",
        translation_key="cost_this_month",
        value_fn=lambda d: period_total(d, dt_util.now().date(), "cost"),
        **MONEY,
    ),
    EnecoSensorDescription(
        key="cost_previous_month",
        translation_key="cost_previous_month",
        value_fn=lambda d: period_total(d, dt_util.now().date(), "cost", True),
        **MONEY,
    ),
    EnecoSensorDescription(
        key="advance_payment",
        translation_key="advance_payment",
        value_fn=lambda d: d["advice"].get("current"),
        **MONEY,
    ),
    EnecoSensorDescription(
        key="advance_payment_advice",
        translation_key="advance_payment_advice",
        value_fn=lambda d: d["advice"].get("advice"),
        **MONEY,
    ),
    EnecoSensorDescription(
        key="forecast_difference",
        translation_key="forecast_difference",
        value_fn=lambda d: d["advice"].get(
            "differenceUsagesCostsTotalAndAdvancePaymentAmountTotal"
        ),
        **MONEY,
    ),
    EnecoSensorDescription(
        key="usage_date",
        translation_key="usage_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=latest_day,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: EnecoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add the heat account's sensors."""
    async_add_entities(EnecoSensor(entry.runtime_data, description) for description in SENSORS)


class EnecoSensor(CoordinatorEntity[EnecoCoordinator], SensorEntity):
    """A value from the portal; period totals deliberately have no state class."""

    _attr_has_entity_name = True
    entity_description: EnecoSensorDescription

    def __init__(self, coordinator: EnecoCoordinator, description: EnecoSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        account_key = f"{coordinator.customer_id}_{coordinator.account_id}"
        self._attr_unique_id = f"{account_key}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, account_key)},
            name="Eneco",
            manufacturer="Eneco",
            model="Mijn Eneco warmte",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.eneco.nl/mijn-eneco/",
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        if self.entity_description.key.startswith(("heat_", "cost_")):
            day = latest_day(self.coordinator.data)
            return {"data_through": day.isoformat()} if day else None
        return None
