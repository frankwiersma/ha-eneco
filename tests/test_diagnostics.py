"""Diagnostics must never contain credentials, cookies, ids or location."""

import json
from types import SimpleNamespace

from custom_components.eneco.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redact_private_data():
    entry = SimpleNamespace(
        data={
            "username": "test@example.invalid",
            "password": "test-password",
            "cookies": [{"name": "test", "value": "synthetic"}],
            "customer_id": 11,
            "account_id": 22,
        },
        runtime_data=SimpleNamespace(
            statistics=SimpleNamespace(heat={"unit_of_measurement": "GJ"}),
            statistics_through=None,
            data={
                "usages": [{"entries": [{"weather": {"location": {"lat": 52.0, "lon": 5.0}}}]}],
                "advice": {"current": 1},
            },
        ),
    )
    text = json.dumps(await async_get_config_entry_diagnostics(None, entry))
    for secret in ("test@example.invalid", "test-password", "synthetic", "52.0", "11", "22"):
        assert secret not in text
