"""Mijn Eneco client. Interactive login respects Eneco's verification challenges.

The portal session can outlive its API token. API rejection is reported to the caller; this client never assumes a session
request renews a token.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from http.cookies import SimpleCookie
from typing import Any

import aiohttp
from yarl import URL

SITE = "https://www.eneco.nl"
SESSION_URL = f"{SITE}/mijn-eneco/api/auth/session"
IDX_URL = "https://inloggen.eneco.nl/idp/idx"
ION = "application/ion+json; okta-version=1.0.0"
TIMEOUT = aiohttp.ClientTimeout(total=30)
COOKIE_DOMAINS = ("eneco.nl",)


class EnecoError(Exception):
    """Eneco could not be reached or answered unexpectedly."""


class EnecoAuthError(EnecoError):
    """Eneco rejected the login, or the stored session is gone."""


class EnecoCodeRequired(EnecoError):
    """Eneco emailed a verification code that has to be entered."""


def amount(value: dict[str, Any] | None) -> float | None:
    """Turn Eneco's {"scale": 5, "value": 2000} into 0.02."""
    if not value or value.get("value") is None:
        return None
    return value["value"] / 10 ** value.get("scale", 0)


class EnecoClient:
    """Logs in to Mijn Eneco and reads usage, costs and the advance payment."""

    def __init__(self, session: aiohttp.ClientSession, username: str, password: str) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._api_host: str | None = None
        self._api_key: str | None = None
        self._pending: dict[str, Any] | None = None

    # Cookies ---------------------------------------------------------------

    def export_cookies(self) -> list[dict[str, str]]:
        """The Eneco and Okta cookies, to restore the session after a restart."""
        return [
            {
                "name": c.key,
                "value": c.value,
                "domain": c["domain"],
                "path": c["path"] or "/",
                "expires": c["expires"],
                "secure": "true" if c["secure"] else "",
            }
            for c in self._session.cookie_jar
            if any(
                (c["domain"].lstrip(".") == d or c["domain"].lstrip(".").endswith("." + d))
                for d in COOKIE_DOMAINS
            )
        ]

    def import_cookies(self, cookies: list[dict[str, str]]) -> None:
        """Put stored cookies back into the session's cookie jar."""
        for c in cookies:
            domain = c["domain"].lstrip(".")
            if not (domain == "eneco.nl" or domain.endswith(".eneco.nl")):
                continue
            url = URL.build(scheme="https", host=domain, path=c["path"])
            jar = SimpleCookie()
            jar[c["name"]] = c["value"]
            for field in ("domain", "path", "expires"):
                jar[c["name"]][field] = c.get(field, "")
            jar[c["name"]]["secure"] = True
            self._session.cookie_jar.update_cookies(jar, url)

    # Login -----------------------------------------------------------------

    async def login(self, code: str | None = None) -> None:
        """Log in, or continue a login with the emailed verification code.

        Raises EnecoCodeRequired when Eneco asks for a code; call login(code) next.
        """
        if code is None or self._pending is None:
            state = await self._start_login()
        else:
            state = self._pending
        for _ in range(10):
            if "success" in state:
                async with self._session.get(
                    _trusted_url(state["success"]["href"], {"www.eneco.nl", "inloggen.eneco.nl"}),
                    timeout=TIMEOUT,
                ) as resp:
                    await resp.read()
                self._pending = None
                await self.session()
                return
            forms = {f["name"]: f for f in state.get("remediation", {}).get("value", [])}
            if "identify" in forms:
                body: dict[str, Any] = {"identifier": self._username}
                if any(v["name"] == "credentials" for v in forms["identify"]["value"]):
                    body["credentials"] = {"passcode": self._password}
                state = await self._idx(forms["identify"], state, body)
            elif "challenge-authenticator" in forms:
                kind = _authenticator_type(state)
                if kind == "password":
                    secret = self._password
                elif code is None:
                    self._pending = state
                    raise EnecoCodeRequired(f"Eneco wants a {kind} code")
                else:
                    secret, code = code.strip(), None
                state = await self._idx(
                    forms["challenge-authenticator"], state, {"credentials": {"passcode": secret}}
                )
            elif "select-authenticator-authenticate" in forms:
                form = forms["select-authenticator-authenticate"]
                state = await self._idx(form, state, {"authenticator": _pick_authenticator(form)})
            else:
                raise EnecoError(f"Unsupported login step: {', '.join(forms) or 'none'}")
        raise EnecoError("Login did not finish")

    async def _start_login(self) -> dict[str, Any]:
        async with self._session.get(f"{SITE}/mijn-eneco/", timeout=TIMEOUT) as resp:
            await resp.read()
        async with self._session.get(f"{SITE}/mijn-eneco/api/auth/csrf/", timeout=TIMEOUT) as resp:
            csrf = (await resp.json(content_type=None))["csrfToken"]
        form = {"csrfToken": csrf, "callbackUrl": "/mijn-eneco/", "json": "true"}
        async with self._session.post(
            f"{SITE}/mijn-eneco/api/auth/signin/okta/", data=form, timeout=TIMEOUT
        ) as resp:
            authorize_url = (await resp.json(content_type=None))["url"]
        async with self._session.get(
            _trusted_url(authorize_url, {"www.eneco.nl", "inloggen.eneco.nl"}), timeout=TIMEOUT
        ) as resp:
            html = await resp.text()
        match = re.search(r'"stateToken":"(.*?)"', html)
        if not match:
            raise EnecoError("Eneco's sign-in page has no state token")
        token = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m[1], 16)), match[1])
        return await self._idx_post(f"{IDX_URL}/introspect", {"stateToken": token})

    async def _idx(
        self, form: dict[str, Any], state: dict[str, Any], body: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._idx_post(form["href"], {**body, "stateHandle": state["stateHandle"]})

    async def _idx_post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": ION, "Accept": ION}
        async with self._session.post(
            _trusted_url(url, {"inloggen.eneco.nl"}),
            json=body,
            headers=headers,
            timeout=TIMEOUT,
            allow_redirects=False,
        ) as resp:
            state = await resp.json(content_type=None)
            if resp.status >= 400:
                messages = [m.get("message") for m in state.get("messages", {}).get("value", [])]
                if resp.status in (400, 401, 403):
                    raise EnecoAuthError("; ".join(filter(None, messages)) or f"HTTP {resp.status}")
                raise EnecoError(f"Login step failed with HTTP {resp.status}")
            return state

    # Data ------------------------------------------------------------------

    async def session(self) -> dict[str, Any]:
        """Read the portal session; its API token may already have expired."""
        async with self._session.get(SESSION_URL, timeout=TIMEOUT) as resp:
            if resp.status in (401, 403):
                raise EnecoAuthError("The Mijn Eneco session expired")
            if resp.status != 200:
                raise EnecoError(f"Session request failed with HTTP {resp.status}")
            session = await resp.json(content_type=None)
        if not session or "accessToken" not in session:
            raise EnecoAuthError("No Mijn Eneco session")
        return session

    async def account(self) -> tuple[int, int]:
        """Customer id and the id of the active energy account."""
        session = await self.session()
        customer_id = int(session["user"]["customerId"])
        profile = await self._get(session, f"/dxpweb/nl/eneco/customers/{customer_id}/profile")
        accounts = profile["data"]["accounts"]
        if not accounts:
            raise EnecoError("No Eneco accounts found")
        active = next((a for a in accounts if a.get("active")), accounts[0])
        return customer_id, int(active["accountId"])

    async def snapshot(self, customer_id: int, account_id: int, today: date) -> dict[str, Any]:
        """Daily usage from the first of last month, plus the advance payment advice."""
        session = await self.session()
        base = f"/nl/eneco/customers/{customer_id}/accounts/{account_id}"
        start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        end = today + timedelta(days=1)
        usages = await self._get(
            session,
            f"/dxpweb/v3{base}/usages",
            {
                "interval": "Day",
                "aggregation": "Day",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "extrapolate": "false",
                "addWeather": "false",
                "addPreviousYear": "false",
                "addBudget": "false",
            },
        )
        advice = await self._get(session, f"/dxpweb/v2{base}/advancepayment/advice")
        return {"usages": usages["data"]["usages"], "advice": advice["data"]}

    async def _get(
        self, session: dict[str, Any], path: str, params: dict[str, str] | None = None
    ) -> Any:
        host, key = await self._api_config()
        headers = {
            "Authorization": f"Bearer {session['accessToken']}",
            "apikey": key,
            "Accept": "application/json",
        }
        async with self._session.get(
            f"{host}{path}", params=params, headers=headers, timeout=TIMEOUT, allow_redirects=False
        ) as resp:
            if resp.status in (401, 403):
                self._api_key = None  # Eneco may have rotated the public API key
                raise EnecoAuthError("Eneco rejected the API token; sign in again")
            if resp.status != 200:
                raise EnecoError(f"GET {path} failed with HTTP {resp.status}")
            return await resp.json(content_type=None)

    async def _api_config(self) -> tuple[str, str]:
        """The API host and public API key, read from Mijn Eneco's page config."""
        if self._api_host and self._api_key:
            return self._api_host, self._api_key
        async with self._session.get(f"{SITE}/mijn-eneco/", timeout=TIMEOUT) as resp:
            html = await resp.text()
        host = re.search(r'"FE_DC_HOST"\s*:\s*"([^"]+)"', html)
        key = re.search(r'"FE_DC_API_KEY"\s*:\s*"([^"]+)"', html)
        if not key:
            raise EnecoError("Mijn Eneco's page config has no API key")
        self._api_host = _trusted_url(
            host[1] if host else "https://api-digital.enecogroup.com",
            {"api-digital.enecogroup.com"},
        ).rstrip("/")
        self._api_key = key[1]
        return self._api_host, self._api_key


def _authenticator_type(state: dict[str, Any]) -> str:
    for key in ("currentAuthenticatorEnrollment", "currentAuthenticator"):
        value = state.get(key, {}).get("value")
        if value and value.get("type"):
            return value["type"]
    return "unknown"


def _pick_authenticator(form: dict[str, Any]) -> dict[str, str]:
    """Prefer the password, then email, as the factor to verify with."""
    field = next(v for v in form["value"] if v["name"] == "authenticator")
    options = field.get("options", [])

    def fields(option: dict[str, Any]) -> dict[str, str]:
        return {v["name"]: v.get("value") for v in option["value"]["form"]["value"] if "value" in v}

    for wanted in ("password", "email"):
        for option in options:
            values = fields(option)
            if values.get("methodType") == wanted or wanted in option.get("label", "").lower():
                return values
    if not options:
        raise EnecoError("No way to verify the login")
    return fields(options[0])


def _trusted_url(url: str, hosts: set[str]) -> str:
    """Do not send credentials to a URL supplied outside Eneco's known origins."""
    parsed = URL(url)
    if (
        parsed.scheme != "https"
        or parsed.host not in hosts
        or parsed.user is not None
        or parsed.port != 443
    ):
        raise EnecoError("Unexpected Eneco service URL")
    return url
