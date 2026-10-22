"""Diagnostics without credentials, session cookies, account ids or location."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_ACCOUNT_ID, CONF_COOKIES, CONF_CUSTOMER_ID
from .coordinator import EnecoConfigEntry

TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_COOKIES,
    CONF_CUSTOMER_ID,
    CONF_ACCOUNT_ID,
    "customerId",
    "accountId",
    "location",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EnecoConfigEntry
) -> dict[str, Any]:
    """Return the entry and the latest portal snapshot."""
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "statistics": {
            "heat": coordinator.statistics.heat["unit_of_measurement"],
            "imported_through": coordinator.statistics_through,
        },
        "snapshot": async_redact_data(coordinator.data, TO_REDACT),
    }
