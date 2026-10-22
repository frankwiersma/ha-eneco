# Eneco for Home Assistant

Read your Mijn Eneco **district heating** consumption, costs and advance payment in Home Assistant. Unofficial integration, installed through HACS, with Dutch and English translations.

**Early release (0.3.1).** Normal sign-in, reading a real heat account, restoring its saved session and repeating normal sign-in have been tested live. Email-code handling, expired-token recovery and the hourly statistics import are covered by automated tests, the import against a real recorder.

## Install

[![Open this repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=frankwiersma&repository=ha-eneco&category=integration)

Open the button, or add `https://github.com/frankwiersma/ha-eneco` to **HACS → Custom repositories**, category **Integration**. Install Eneco and restart Home Assistant.

For manual installation, copy `custom_components/eneco` to your Home Assistant configuration's `custom_components` directory and restart. Home Assistant **2026.10 or newer** is required.

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

These are portal figures, not live meter readings. Period totals deliberately have no statistics state class: they are **not cumulative meter counters**. For the Energy dashboard, use the imported statistics below. Electricity, gas and multiple-account selection are outside this release.

## Energy dashboard

The integration imports Eneco's hourly heat readings as long-term statistics, at the hour they were measured rather than the moment Eneco publishes them:

| Statistic | Unit | Meaning |
|---|---|---|
| Eneco heat | GJ | Measured heat per hour |
| Eneco heat cost | EUR | Usage cost per hour including VAT, without fixed charges |
| Eneco heat fixed cost | EUR | Fixed charges per hour including VAT (standing charge, delivery) |

Go to **Settings → Dashboards → Energy → Gas consumption → Add gas source**, choose **Eneco heat**, and under costs choose **Use an entity tracking the total costs** with **Eneco heat cost**. Home Assistant has no separate heat source; the gas source accepts GJ. Name the source, for example, *Stadswarmte*.

On first start the integration fills the full history. Daily readings mark where it starts: it walks back a month at a time until a month without readings. From the first day with every hour measured, hours are imported as they are. Before that, Eneco's hourly data is partial (at the start of a contract it can hold only the first hour of each day), so those days come in as one row at local midnight with the day's total. After that, every refresh imports the new hours, since Eneco reports hours during the day, and rewrites the three days before the last imported hour, so late fills and corrections from Eneco end up in the totals. Eneco labels readings with Dutch local time; the import converts them to UTC, including the repeated hour when daylight saving time ends. The Energy dashboard gets the usage cost, because fixed charges are not caused by consumption. The fixed charges have their own statistic, so a chart can stack both into the full cost; the cost sensors above include them too. A statistic added by an update gets the full history on its first run.

## Privacy

Your credentials and Eneco session cookies are stored locally in Home Assistant's config entry and included in its backups. Requests go directly to Eneco and its API host. There is no telemetry or external proxy. Email verification codes are used in memory during setup and are not stored in the entry. A dedicated HTTP session isolates Eneco cookies from other integrations.

Never include credentials, cookies, tokens or unredacted account responses in issues. **Download diagnostics** on the integration page gives a snapshot without credentials, cookies, account numbers or location.

## Development

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
```

Tests use synthetic data and make no calls to Eneco. They run on Home Assistant's own test harness for custom integrations, pinned to the supported release. CI runs tests, Ruff, Hassfest and HACS validation. The client follows the API used by [Mijn Eneco](https://www.eneco.nl/mijn-eneco/); this API can change without notice.

## Disclaimer

Not affiliated with or endorsed by Eneco. Eneco is a trademark of its owner. This integration only reads account data; it does not change payments, contracts or account settings. MIT licensed.
