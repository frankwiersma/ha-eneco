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


def warmth(usage, fixed):
    """Usage in MJ, fixed cost in cents; usage costs 4 cents per MJ."""
    return {
        "status": "MEASURED",
        "high": {"scale": 3, "value": usage},
        "low": {"scale": 3, "value": 0},
        "totalUsageCostInclVat": {"scale": 2, "value": usage * 4},
        "fixedCostInclVat": {"scale": 2, "value": fixed},
        "totalCostInclVat": {"scale": 2, "value": usage * 4 + fixed},
    }


class FakeEneco:
    """Serves the usages API: full hours per day, or before hourly metering a daily
    total with only the first hour in the hourly data, as Eneco does."""

    def __init__(self, hourly, daily_only=()):
        self.hourly = hourly  # day -> 24 usages
        self.daily_only = dict(daily_only)  # day -> usage of the whole day
        self.requests = []

    def _range(self, start, end):
        day = start
        while day < end:
            yield day
            day += timedelta(days=1)

    async def days(self, customer_id, account_id, start, end):
        self.requests.append(("Day", start, end))
        entries = []
        for day in self._range(start, end):
            if day in self.hourly:
                total = warmth(sum(self.hourly[day]), 7 * 24)
            elif day in self.daily_only:
                total = warmth(self.daily_only[day], 7 * 24)
            else:
                continue
            entries.append({"actual": {"date": f"{day.isoformat()}T00:00:00Z", "warmth": total}})
        return [{"entries": entries}]

    async def hours(self, customer_id, account_id, start, end):
        self.requests.append(("Hour", start, end))
        entries = []
        for day in self._range(start, end):
            usages = self.hourly.get(day) or ([0] if day in self.daily_only else [])
            for hour, usage in enumerate(usages):
                entries.append(
                    {
                        "actual": {
                            "date": f"{day.isoformat()}T{hour:02d}:00:00Z",
                            "warmth": warmth(usage, 7),
                        }
                    }
                )
        return [{"entries": entries}]


def days(first, last, value):
    result, day = {}, first
    while day <= last:
        result[day] = value
        day += timedelta(days=1)
    return result


async def read(hass, statistic_id, period="hour"):
    await async_wait_recording_done(hass)
    rows = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2026, 1, 1, tzinfo=UTC),
        None,
        {statistic_id},
        period,
        None,
        {"state", "sum"},
    )
    return rows.get(statistic_id, [])


@pytest.fixture
async def setup(recorder_mock, hass):
    eneco = FakeEneco(
        hourly=days(date(2026, 9, 10), date(2026, 10, 20), [1] * 24),
        daily_only=days(date(2026, 9, 1), date(2026, 9, 9), 5),
    )
    return eneco, EnecoStatistics(hass, eneco, 1, 2)


async def test_backfill_uses_daily_totals_before_hourly_metering(setup, hass):
    eneco, stats = setup
    await stats.async_update(date(2026, 10, 22))
    heat = await read(hass, HEAT)
    assert len(heat) == 9 + 41 * 24
    assert heat[0]["start"] == datetime(2026, 8, 31, 22, tzinfo=UTC).timestamp()
    assert heat[0]["state"] == pytest.approx(0.005)  # 1 September, the whole day
    assert heat[9]["start"] == datetime(2026, 9, 9, 22, tzinfo=UTC).timestamp()
    assert heat[-1]["sum"] == pytest.approx(9 * 0.005 + 41 * 24 * 0.001)
    assert (await read(hass, COST))[-1]["sum"] == pytest.approx(9 * 0.2 + 41 * 24 * 0.04)
    assert (await read(hass, FIXED))[-1]["sum"] == pytest.approx(50 * 24 * 0.07)
    assert [r for r in eneco.requests if r[0] == "Day"] == [
        ("Day", date(2026, 9, 22), date(2026, 10, 23)),
        ("Day", date(2026, 8, 22), date(2026, 9, 22)),
        ("Day", date(2026, 7, 22), date(2026, 8, 22)),
    ]
    metadata = await get_instance(hass).async_add_executor_job(get_metadata, hass)
    assert metadata[HEAT][1]["unit_of_measurement"] == "GJ"
    assert metadata[HEAT][1]["unit_class"] == "energy"
    assert metadata[COST][1]["unit_of_measurement"] == "EUR"


async def test_update_rewrites_recent_days_and_continues_the_total(setup, hass):
    eneco, stats = setup
    await stats.async_update(date(2026, 10, 22))
    before = {row["start"]: row["sum"] for row in await read(hass, HEAT)}

    eneco.hourly[date(2026, 10, 19)] = [2] * 24  # Eneco corrects a recent day
    eneco.hourly[date(2026, 10, 21)] = [1] * 24  # and reports a new one
    eneco.requests.clear()
    await stats.async_update(date(2026, 10, 23))

    assert eneco.requests == [("Hour", date(2026, 10, 17), date(2026, 10, 24))]
    heat = await read(hass, HEAT)
    assert len(heat) == 9 + 42 * 24
    untouched = datetime(2026, 10, 16, 21, tzinfo=UTC).timestamp()
    assert {r["start"]: r["sum"] for r in heat}[untouched] == before[untouched]
    assert heat[-1]["sum"] == pytest.approx(9 * 0.005 + (42 * 24 + 24) * 0.001)
    sums = [row["sum"] for row in heat]
    assert sums == sorted(sums)


async def test_statistic_added_by_an_update_gets_full_history(setup, hass):
    eneco, stats = setup
    stats.series = stats.series[:2]  # the release before fixed costs
    await stats.async_update(date(2026, 10, 22))
    assert await read(hass, FIXED) == []

    updated = EnecoStatistics(hass, eneco, 1, 2)
    await updated.async_update(date(2026, 10, 22))
    assert len(await read(hass, FIXED)) == 9 + 41 * 24
    assert (await read(hass, HEAT))[-1]["sum"] == pytest.approx(9 * 0.005 + 41 * 24 * 0.001)

    eneco.requests.clear()
    await updated.async_update(date(2026, 10, 22))
    assert eneco.requests == [("Hour", date(2026, 10, 17), date(2026, 10, 23))]
