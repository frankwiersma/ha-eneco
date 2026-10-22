"""Exercise the HA flow's multi-step lifecycle without contacting Eneco."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.eneco.api import EnecoCodeRequired
from custom_components.eneco.config_flow import EnecoConfigFlow


async def test_mfa_flow_and_cancellation_release_session():
    flow = EnecoConfigFlow()
    tasks = []
    flow.hass = SimpleNamespace(async_create_task=tasks.append)
    flow.context = {"source": "user"}
    session = SimpleNamespace(close=AsyncMock())
    with (
        patch(
            "custom_components.eneco.config_flow.async_create_clientsession", return_value=session
        ),
        patch("custom_components.eneco.config_flow.EnecoClient") as cls,
    ):
        cls.return_value.login = AsyncMock(side_effect=EnecoCodeRequired())
        result = await flow.async_step_user(
            {"username": "test@example.invalid", "password": "synthetic-password"}
        )
    assert result["step_id"] == "code"
    assert flow._client is not None
    session.close.assert_not_awaited()
    flow.async_remove()
    for task in tasks:
        await task
    session.close.assert_awaited_once()
    assert flow._client is None


async def test_success_saves_credentials_and_session_but_never_code():
    flow = EnecoConfigFlow()
    flow.context = {"source": "user"}
    flow._username = "test@example.invalid"
    flow._password = "synthetic-password"
    flow._session = SimpleNamespace(close=AsyncMock())
    client = SimpleNamespace(
        account=AsyncMock(return_value=(1, 2)),
        snapshot=AsyncMock(return_value={}),
        export_cookies=lambda: [],
    )
    flow._client = client
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    result = await flow._finish()
    assert result["data"] == {
        "username": "test@example.invalid",
        "password": "synthetic-password",
        "customer_id": 1,
        "account_id": 2,
        "cookies": [],
    }
    assert flow._session is None
    assert flow._client is None


async def test_reauth_updates_existing_entry():
    flow = EnecoConfigFlow()
    flow.context = {"source": "reauth"}
    flow._username = "test@example.invalid"
    flow._password = "synthetic-password"
    flow._client = SimpleNamespace(
        account=AsyncMock(return_value=(1, 2)), snapshot=AsyncMock(), export_cookies=lambda: []
    )
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_mismatch = MagicMock()
    flow._get_reauth_entry = MagicMock(return_value="entry")
    flow.async_update_reload_and_abort = MagicMock(return_value={"type": "abort"})
    await flow._finish()
    flow._abort_if_unique_id_mismatch.assert_called_once_with(reason="wrong_account")
    flow.async_update_reload_and_abort.assert_called_once()
