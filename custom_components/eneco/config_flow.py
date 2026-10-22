"""Interactive Eneco sign-in, including emailed verification codes."""

from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType
from homeassistant.util import dt as dt_util

from .api import EnecoAuthError, EnecoClient, EnecoCodeRequired, EnecoError
from .const import CONF_ACCOUNT_ID, CONF_COOKIES, CONF_CUSTOMER_ID, DOMAIN

LOGIN_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
        ),
    }
)
CODE_SCHEMA = vol.Schema({vol.Required("code"): str})


class EnecoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Keep login state in memory only until setup finishes or is cancelled."""

    VERSION = 1

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._client: EnecoClient | None = None
        self._username = ""
        self._password = ""

    async def _close(self) -> None:
        if self._session is not None:
            await self._session.close()
        self._session = None
        self._client = None
        self._password = ""

    @callback
    def async_remove(self) -> None:
        """Also close the session when a user cancels or a flow expires."""
        if self._session is not None:
            self.hass.async_create_task(self._close())
        super().async_remove()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            await self._close()
            self._username = user_input[CONF_USERNAME].strip()
            self._password = user_input[CONF_PASSWORD]
            self._session = async_create_clientsession(
                self.hass, auto_cleanup=False, cookie_jar=aiohttp.CookieJar()
            )
            self._client = EnecoClient(self._session, self._username, user_input[CONF_PASSWORD])
            try:
                await self._client.login()
                return await self._finish()
            except EnecoCodeRequired:
                return await self.async_step_code()
            except EnecoAuthError:
                errors["base"] = "invalid_auth"
            except EnecoError, aiohttp.ClientError, TimeoutError, KeyError, TypeError, ValueError:
                errors["base"] = "cannot_connect"
            await self._close()
        return self.async_show_form(step_id="user", data_schema=LOGIN_SCHEMA, errors=errors)

    async def async_step_code(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = {}
        if self._client is None:
            return await self.async_step_user()
        if user_input is not None:
            try:
                await self._client.login(user_input["code"])
                return await self._finish()
            except EnecoAuthError, EnecoCodeRequired:
                errors["base"] = "invalid_code"
            except EnecoError, aiohttp.ClientError, TimeoutError, KeyError, TypeError, ValueError:
                await self._close()
                return self.async_abort(reason="cannot_connect")
        return self.async_show_form(step_id="code", data_schema=CODE_SCHEMA, errors=errors)

    async def _finish(self) -> ConfigFlowResult:
        assert self._client is not None
        customer, account = await self._client.account()
        # Validate both permissions and payloads before saving a working entry.
        await self._client.snapshot(customer, account, dt_util.now().date())
        data = {
            CONF_USERNAME: self._username,
            CONF_PASSWORD: self._password,
            CONF_CUSTOMER_ID: customer,
            CONF_ACCOUNT_ID: account,
            CONF_COOKIES: self._client.export_cookies(),
        }
        await self._close()
        await self.async_set_unique_id(f"{customer}_{account}")
        if self.source == "reauth":
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=data)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Eneco", data=data)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Expired API tokens lead back through the same interactive sign-in."""
        return await self.async_step_user()
