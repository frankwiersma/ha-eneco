"""Synthetic fixtures only; no account identifiers, real tokens or cookies."""

from datetime import date
from http.cookies import SimpleCookie
from unittest.mock import AsyncMock

import aiohttp
import pytest
from aioresponses import aioresponses
from yarl import URL

from custom_components.eneco.api import (
    IDX_URL,
    SESSION_URL,
    SITE,
    EnecoAuthError,
    EnecoClient,
    EnecoCodeRequired,
    EnecoError,
    _trusted_url,
    amount,
)


async def test_expired_token_requests_reauth_without_logging_in():
    async with aiohttp.ClientSession() as session:
        client = EnecoClient(session, "", "")
        client._api_host, client._api_key = "https://api-digital.enecogroup.com", "public-test"
        client.login = AsyncMock()
        with aioresponses() as mock:
            mock.get("https://api-digital.enecogroup.com/test", status=403)
            with pytest.raises(EnecoAuthError):
                await client._get({"accessToken": "expired-test-token"}, "/test")
        client.login.assert_not_called()


async def test_mfa_pauses_and_resumes_with_entered_code():
    state = {
        "stateHandle": "test-handle",
        "currentAuthenticator": {"value": {"type": "email"}},
        "remediation": {
            "value": [{"name": "challenge-authenticator", "href": f"{IDX_URL}/challenge/answer"}]
        },
    }
    async with aiohttp.ClientSession() as session:
        client = EnecoClient(session, "test@example.invalid", "test-password")
        client._start_login = AsyncMock(return_value=state)
        with pytest.raises(EnecoCodeRequired):
            await client.login()
        assert client._pending == state
        with aioresponses() as mock:
            mock.post(
                f"{IDX_URL}/challenge/answer", payload={"success": {"href": f"{SITE}/callback"}}
            )
            mock.get(f"{SITE}/callback", status=200)
            mock.get(SESSION_URL, payload={"accessToken": "test-token"})
            await client.login("123456")
            request = mock.requests[("POST", URL(f"{IDX_URL}/challenge/answer"))][0]
            assert request.kwargs["json"]["credentials"]["passcode"] == "123456"
        assert client._pending is None
        assert client._start_login.await_count == 1


async def test_incorrect_code_keeps_challenge_for_retry():
    async with aiohttp.ClientSession() as session:
        client = EnecoClient(session, "", "")
        client._pending = {
            "stateHandle": "test-handle",
            "currentAuthenticator": {"value": {"type": "email"}},
            "remediation": {
                "value": [{"name": "challenge-authenticator", "href": f"{IDX_URL}/answer"}]
            },
        }
        with aioresponses() as mock:
            mock.post(f"{IDX_URL}/answer", status=401, payload={})
            with pytest.raises(EnecoAuthError):
                await client.login("000000")
        assert client._pending is not None


async def test_missing_session_is_auth_failure():
    async with aiohttp.ClientSession() as session:
        with aioresponses() as mock:
            mock.get(SESSION_URL, payload={})
            with pytest.raises(EnecoAuthError):
                await EnecoClient(session, "", "").session()


async def test_server_failure_is_not_invalid_auth():
    async with aiohttp.ClientSession() as session:
        with aioresponses() as mock:
            mock.get(SESSION_URL, status=503)
            with pytest.raises(EnecoError) as err:
                await EnecoClient(session, "", "").session()
            assert not isinstance(err.value, EnecoAuthError)


async def test_cookie_roundtrip_preserves_path_expiry_and_domain():
    async with aiohttp.ClientSession() as first, aiohttp.ClientSession() as second:
        cookies = SimpleCookie()
        cookies["test-session"] = "synthetic-value"
        cookies["test-session"]["domain"] = "www.eneco.nl"
        cookies["test-session"]["path"] = "/mijn-eneco"
        cookies["test-session"]["expires"] = "Wed, 01 Jan 2031 00:00:00 GMT"
        cookies["test-session"]["secure"] = True
        first.cookie_jar.update_cookies(cookies, URL(SITE))
        client = EnecoClient(first, "", "")
        restored = EnecoClient(second, "", "")
        restored.import_cookies(client.export_cookies())
        assert restored.export_cookies() == client.export_cookies()
        assert not second.cookie_jar.filter_cookies(URL("https://unrelated.invalid/mijn-eneco"))
        assert not second.cookie_jar.filter_cookies(URL(f"{SITE}/other"))


async def test_previous_month_query_handles_january():
    async with aiohttp.ClientSession() as session:
        client = EnecoClient(session, "", "")
        client.session = AsyncMock(return_value={"accessToken": "test"})
        client._get = AsyncMock(side_effect=[{"data": {"usages": []}}, {"data": {}}])
        await client.snapshot(1, 2, date(2026, 1, 2))
        params = client._get.call_args_list[0].args[2]
        assert params["start"] == "2025-12-01"
        assert params["end"] == "2026-01-03"


@pytest.mark.parametrize(
    "url",
    [
        "https://eneco.nl.attacker.invalid/a",
        "http://www.eneco.nl",
        "https://user@www.eneco.nl",
        "https://www.eneco.nl:444",
    ],
)
def test_rejects_credential_redirects(url):
    with pytest.raises(EnecoError):
        _trusted_url(url, {"www.eneco.nl"})


def test_scaled_amount_zero_and_missing():
    assert amount({"value": 2000, "scale": 5}) == 0.02
    assert amount({"value": 0, "scale": 5}) == 0
    assert amount(None) is None


async def test_authorize_can_complete_by_redirect_without_idx_challenge():
    async with aiohttp.ClientSession() as session:
        client = EnecoClient(session, "", "")
        with aioresponses() as mock:
            mock.get(f"{SITE}/mijn-eneco/", body="portal")
            mock.get(f"{SITE}/mijn-eneco/api/auth/csrf/", payload={"csrfToken": "test-csrf"})
            mock.post(
                f"{SITE}/mijn-eneco/api/auth/signin/okta/",
                payload={"url": "https://inloggen.eneco.nl/authorize"},
            )
            mock.get("https://inloggen.eneco.nl/authorize", body="portal after completed callback")
            mock.get(SESSION_URL, payload={"accessToken": "test-renewed-token"})
            mock.get(f"{SITE}/mijn-eneco/", body="portal")
            mock.get(SESSION_URL, payload={"accessToken": "test-renewed-token"})
            await client.login()
