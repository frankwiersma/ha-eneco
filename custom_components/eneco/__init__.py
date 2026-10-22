"""Eneco heat usage for Home Assistant."""

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import EnecoConfigEntry, EnecoCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: EnecoConfigEntry) -> bool:
    """Start polling with the stored session."""
    coordinator = EnecoCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await coordinator.session.close()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EnecoConfigEntry) -> bool:
    """Unload sensors and release the dedicated cookie session."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.session.close()
    return unloaded
