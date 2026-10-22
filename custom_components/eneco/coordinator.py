"""Poll Eneco and use normal sign-in when a session needs renewal."""

import logging
from datetime import date, datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import EnecoAuthError, EnecoClient, EnecoCodeRequired, EnecoError
from .const import (
    CONF_ACCOUNT_ID,
    CONF_COOKIES,
    CONF_CUSTOMER_ID,
    DOMAIN,
    UPDATE_INTERVAL_MINUTES,
)
from .data import ENECO_TZ, latest_day
from .statistics import EnecoStatistics

_LOGGER = logging.getLogger(__name__)
type EnecoConfigEntry = ConfigEntry[EnecoCoordinator]


class EnecoCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Own a private session and fetch the account snapshot."""

    def __init__(self, hass: HomeAssistant, entry: EnecoConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        self.session = async_create_clientsession(
            hass, auto_cleanup=False, cookie_jar=aiohttp.CookieJar()
        )
        self.client = EnecoClient(
            self.session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
        )
        self.client.import_cookies(entry.data[CONF_COOKIES])
        self.customer_id = entry.data[CONF_CUSTOMER_ID]
        self.account_id = entry.data[CONF_ACCOUNT_ID]
        self.statistics = EnecoStatistics(hass, self.client, self.customer_id, self.account_id)
        self.statistics_through: date | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            try:
                data = await self.client.snapshot(
                    self.customer_id, self.account_id, dt_util.now().date()
                )
            except EnecoAuthError:
                # One normal login attempt. Never work around an MFA challenge.
                await self.client.login()
                data = await self.client.snapshot(
                    self.customer_id, self.account_id, dt_util.now().date()
                )
        except (EnecoAuthError, EnecoCodeRequired) as err:
            raise ConfigEntryAuthFailed("Sign in to Mijn Eneco again") from err
        except (
            EnecoError,
            aiohttp.ClientError,
            TimeoutError,
            KeyError,
            TypeError,
            ValueError,
        ) as err:
            raise UpdateFailed("Could not read the Eneco usage data") from err
        cookies = self.client.export_cookies()
        if cookies != self.config_entry.data[CONF_COOKIES]:
            self.hass.config_entries.async_update_entry(
                self.config_entry, data={**self.config_entry.data, CONF_COOKIES: cookies}
            )
        await self._async_update_statistics(data)
        return data

    async def _async_update_statistics(self, data: dict[str, Any]) -> None:
        """Import hours once per newly reported day; sensors do not wait on failures."""
        reported = latest_day(data)
        if reported is None or reported == self.statistics_through:
            return
        try:
            await self.statistics.async_update(datetime.now(ENECO_TZ).date())
        except (
            EnecoError,
            aiohttp.ClientError,
            TimeoutError,
            KeyError,
            TypeError,
            ValueError,
        ) as err:
            _LOGGER.warning("Could not import Eneco hourly heat statistics: %s", err)
            return
        self.statistics_through = reported
