"""Hourly import into a real recorder: backfill, corrections and running totals."""

from datetime import UTC, date, datetime, timedelta

import pytest
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    get_metadata,
    statistics_during_period,
)
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.eneco.statistics import EnecoStatistics

HEAT = "eneco:heat_1_2"
COST = "eneco:heat_1_2_cost"
FIXED = "eneco:heat_1_2_fixed_cost"


class FakeEneco:
    """Serves hourly groups for the requested local days, like the usages API."""

    def __init__(self, days):
        self.days = days
        self.requests = []

    async def hours(self, customer_id, account_id, start, end):
        self.requests.append((start, end))
        entries = []
        day = start
        while day < end:
            for hour, usage in enumerate(self.days.get(day, [])):
                entries.append(
                    {
                        "actual": {
                            "date": f"{day.isoformat()}T{hour:02d}:00:00Z",
                            "warmth": {
                                "status": "MEASURED",
                                "high": {"scale": 3, "value": usage},
                                "low": {"scale": 3, "value": 0},
                                "totalUsageCostInclVat": {"scale": 2, "value": usage * 4},
                                "fixedCostInclVat": {"scale": 2, "value": 7},
                            },
                        }
                    }
                )
            day += timedelta(days=1)
        return [{"entries": entries}]


def measured_days(first, last, usage=1):
    days = {}
    day = first
    while day <= last:
        days[day] = [usage] * 24
        day += timedelta(days=1)
    return days


async def read(hass, statistic_id):
    await async_wait_recording_done(hass)
    rows = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2026, 1, 1, tzinfo=UTC),
        None,
        {statistic_id},
        "hour",
        None,
        {"state", "sum"},
    )
    return rows.get(statistic_id, [])


@pytest.fixture
async def setup(recorder_mock, hass):
    eneco = FakeEneco(measured_days(date(2026, 10, 10), date(2026, 10, 20)))
    return eneco, EnecoStatistics(hass, eneco, 1, 2)


async def test_backfill_stops_at_first_week_without_readings(setup, hass):
    eneco, stats = setup
    await stats.async_update(date(2026, 10, 22))
    heat = await read(hass, HEAT)
    assert len(heat) == 11 * 24
    assert heat[0]["start"] == datetime(2026, 10, 9, 22, tzinfo=UTC).timestamp()
    assert heat[-1]["sum"] == pytest.approx(11 * 24 * 0.001)
    assert (await read(hass, COST))[-1]["sum"] == pytest.approx(11 * 24 * 0.04)
    assert (await read(hass, FIXED))[-1]["sum"] == pytest.approx(11 * 24 * 0.07)
    assert eneco.requests == [
        (date(2026, 10, 16), date(2026, 10, 23)),
        (date(2026, 10, 9), date(2026, 10, 16)),
        (date(2026, 10, 2), date(2026, 10, 9)),
    ]
    metadata = await get_instance(hass).async_add_executor_job(get_metadata, hass)
    assert metadata[HEAT][1]["unit_of_measurement"] == "GJ"
    assert metadata[HEAT][1]["unit_class"] == "energy"
    assert metadata[COST][1]["unit_of_measurement"] == "EUR"


async def test_update_rewrites_recent_days_and_continues_the_total(setup, hass):
    eneco, stats = setup
    await stats.async_update(date(2026, 10, 22))
    before = {row["start"]: row["sum"] for row in await read(hass, HEAT)}

    eneco.days[date(2026, 10, 19)] = [2] * 24  # Eneco corrects a recent day
    eneco.days[date(2026, 10, 21)] = [1] * 24  # and reports a new one
    eneco.requests.clear()
    await stats.async_update(date(2026, 10, 23))

    assert eneco.requests == [(date(2026, 10, 17), date(2026, 10, 24))]
    heat = await read(hass, HEAT)
    assert len(heat) == 12 * 24
    untouched = datetime(2026, 10, 16, 21, tzinfo=UTC).timestamp()
    assert {r["start"]: r["sum"] for r in heat}[untouched] == before[untouched]
    assert heat[-1]["sum"] == pytest.approx((12 * 24 + 24) * 0.001)
    sums = [row["sum"] for row in heat]
    assert sums == sorted(sums)


async def test_statistic_added_by_an_update_gets_full_history(setup, hass):
    eneco, stats = setup
    stats.series = stats.series[:2]  # the release before fixed costs
    await stats.async_update(date(2026, 10, 22))
    assert await read(hass, FIXED) == []

    updated = EnecoStatistics(hass, eneco, 1, 2)
    eneco.requests.clear()
    await updated.async_update(date(2026, 10, 22))
    assert len(eneco.requests) == 3  # backfill again, once
    assert len(await read(hass, FIXED)) == 11 * 24
    assert (await read(hass, HEAT))[-1]["sum"] == pytest.approx(11 * 24 * 0.001)

    eneco.requests.clear()
    await updated.async_update(date(2026, 10, 22))
    assert eneco.requests == [(date(2026, 10, 17), date(2026, 10, 23))]
