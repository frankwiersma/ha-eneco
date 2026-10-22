# Eneco for Home Assistant

Read your Mijn Eneco **district heating** consumption, costs and advance payment in Home Assistant. Unofficial integration, installed through HACS, with Dutch and English translations.

**Early release (0.1.0).** Normal sign-in, reading a real heat account, restoring its saved session and repeating normal sign-in have been tested live. Email-code handling and expired-token recovery are covered by automated tests. Long-running operation and installation in a real Home Assistant instance have not yet been verified.

## Install

[![Open this repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=frankwiersma&repository=ha-eneco&category=integration)

Open the button, or add `https://github.com/frankwiersma/ha-eneco` to **HACS → Custom repositories**, category **Integration**. Install Eneco and restart Home Assistant.

For manual installation, copy `custom_components/eneco` to your Home Assistant configuration's `custom_components` directory and restart. Home Assistant **2025.10 or newer** is required.

## Set up

[![Add Eneco to Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=eneco)

Go to **Settings → Devices & services → Add integration → Eneco**. Enter your Mijn Eneco email address and password. If Eneco requests an email verification code, enter it in the next step. The integration selects the first active account returned by Eneco, or the first account if none is marked active. Selecting additional accounts is not currently supported.

Data refreshes every 30 minutes while the integration is loaded. The portal's API token can expire before its website session. When access expires, the integration makes **one normal sign-in attempt** using your stored credentials. If Eneco requires a code or rejects that login, Home Assistant asks you to authenticate again. Codes are entered by you; authentication challenges are never bypassed. An uninterrupted connection without user action cannot be guaranteed.

## Sensors

| Sensor | Unit | Meaning |
|---|---|---|
| Heat latest reported day | GJ | Latest day with measured heat data |
| Heat this month | GJ | Sum of reported measured days in the current calendar month |
| Heat previous month | GJ | Sum of reported measured days in the previous calendar month |
| Heat cost latest reported day | EUR | Reported heat cost, including VAT and fixed heat charges |
| Heat cost this month | EUR | Sum of reported daily heat costs this month |
| Heat cost previous month | EUR | Sum of reported daily heat costs last month |
| Advance payment | EUR | Your current monthly advance payment |
| Recommended advance payment | EUR | Eneco's current recommendation |
| Forecast amount to pay at settlement | EUR | Positive means extra to pay; negative means a forecast refund |
| Usage reported through | date | Date of the latest measured heat data |

Missing data stays unknown. A reported zero remains zero. Forecast consumption is excluded. Month totals cover **available reported days**, so they can change when Eneco fills gaps or corrects a reading. The latest reported day may be several days behind today; consumption sensors include a `data_through` attribute.

These are portal figures, not live meter readings. Period totals deliberately have no statistics state class: they are **not cumulative meter counters** and cannot be selected directly as an Energy dashboard heat source. Historical recorder import and hourly sensors are outside this release. Electricity, gas and multiple-account selection are also outside this release.

## Privacy

Your credentials and Eneco session cookies are stored locally in Home Assistant's config entry and included in its backups. Requests go directly to Eneco and its API host. There is no telemetry or external proxy. Email verification codes are used in memory during setup and are not stored in the entry. A dedicated HTTP session isolates Eneco cookies from other integrations.

Never include credentials, cookies, tokens or unredacted account responses in issues.

## Development

```sh
python3.13 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
```

Tests use synthetic data and make no calls to Eneco. CI runs tests, Ruff, Hassfest and HACS validation. The client follows the API used by [Mijn Eneco](https://www.eneco.nl/mijn-eneco/); this API can change without notice.

## Disclaimer

Not affiliated with or endorsed by Eneco. Eneco is a trademark of its owner. This integration only reads account data; it does not change payments, contracts or account settings. MIT licensed.
