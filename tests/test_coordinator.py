"""Renewal must try normal sign-in once, respect MFA and never loop."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.eneco.api import EnecoAuthError, EnecoCodeRequired, EnecoError
from custom_components.eneco.coordinator import EnecoCoordinator


def coordinator():
    obj = object.__new__(EnecoCoordinator)
    obj.client = SimpleNamespace(snapshot=AsyncMock(), login=AsyncMock(), export_cookies=lambda: [])
    obj.customer_id, obj.account_id = 1, 2
    obj.config_entry = SimpleNamespace(data={"cookies": []})
    obj.hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=MagicMock()))
    return obj


async def test_expired_token_renews_once_and_persists_new_cookies():
    obj = coordinator()
    obj.client.snapshot.side_effect = [EnecoAuthError(), {"usages": []}]
    obj.client.export_cookies = lambda: [{"name": "test", "value": "synthetic"}]
    assert await obj._async_update_data() == {"usages": []}
    obj.client.login.assert_awaited_once()
    obj.hass.config_entries.async_update_entry.assert_called_once()


async def test_mfa_challenge_requires_user_action():
    obj = coordinator()
    obj.client.snapshot.side_effect = EnecoAuthError()
    obj.client.login.side_effect = EnecoCodeRequired()
    with pytest.raises(ConfigEntryAuthFailed):
        await obj._async_update_data()
    obj.client.login.assert_awaited_once()
    assert obj.client.snapshot.await_count == 1


async def test_rejected_renewal_does_not_loop():
    obj = coordinator()
    obj.client.snapshot.side_effect = EnecoAuthError()
    with pytest.raises(ConfigEntryAuthFailed):
        await obj._async_update_data()
    obj.client.login.assert_awaited_once()
    assert obj.client.snapshot.await_count == 2


async def test_outage_does_not_start_login():
    obj = coordinator()
    obj.client.snapshot.side_effect = EnecoError()
    with pytest.raises(UpdateFailed):
        await obj._async_update_data()
    obj.client.login.assert_not_called()
