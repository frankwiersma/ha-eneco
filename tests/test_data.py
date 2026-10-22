"""Verify delayed meter data, missing days, corrections and month boundaries."""

from datetime import UTC, date, datetime

import pytest

from custom_components.eneco.data import (
    heat_days,
    heat_hours,
    latest_day,
    latest_value,
    period_total,
)


def entry(day, high=None, low=None, cost=None, status="MEASURED"):
    return {
        "actual": {
            "date": day,
            "warmth": {"status": status, "high": high, "low": low, "totalCostInclVat": cost},
        }
    }


def snapshot(*entries):
    return {"usages": [{"entries": list(entries)}], "advice": {}}


def test_delayed_days_and_real_zero():
    data = snapshot(
        entry("2026-10-18T00:00:00", {"value": 0}, cost={"value": 220, "scale": 2}),
        entry("2026-10-20", {"value": 999}, status="ESTIMATED"),
    )
    assert latest_day(data) == date(2026, 10, 18)
    assert latest_value(data, "usage") == 0
    assert latest_value(data, "cost") == 2.2
    assert len(heat_days(data)) == 1


def test_empty_is_unknown_not_zero():
    assert latest_value(snapshot(), "usage") is None
    assert period_total(snapshot(), date(2026, 10, 22), "usage") is None


def test_january_previous_month_both_tariffs_and_costs():
    data = snapshot(
        entry(
            "2025-12-31",
            {"value": 12, "scale": 2},
            {"value": 8, "scale": 2},
            {"value": 925, "scale": 2},
        ),
        entry("2026-01-01", {"value": 3, "scale": 2}),
    )
    assert period_total(data, date(2026, 1, 2), "usage", True) == pytest.approx(0.2)
    assert period_total(data, date(2026, 1, 2), "cost", True) == 9.25
    assert period_total(data, date(2026, 1, 2), "usage") == 0.03


def test_corrected_day_is_not_counted_twice():
    data = snapshot(entry("2026-10-01", {"value": 2}), entry("2026-10-01", {"value": 1}))
    assert period_total(data, date(2026, 10, 22), "usage") == 1


def hour(label, high=None, low=None, cost=None, status="MEASURED"):
    return {
        "actual": {
            "date": label,
            "warmth": {"status": status, "high": high, "low": low, "totalUsageCostInclVat": cost},
        }
    }


def test_hours_are_dutch_wall_clock_in_utc():
    hours = heat_hours(
        [
            {
                "entries": [
                    hour("2026-10-21T00:00:00Z", {"value": 1, "scale": 2}, cost={"value": 4}),
                    hour("2026-10-21T01:00:00Z", {"value": 0}),
                    hour("2026-10-21T02:00:00Z", {"value": 9}, status="ESTIMATED"),
                    hour("2026-10-21T03:00:00Z"),
                ]
            }
        ]
    )
    assert hours == {
        datetime(2026, 10, 20, 22, tzinfo=UTC): {"usage": 0.01, "cost": 4},
        datetime(2026, 10, 20, 23, tzinfo=UTC): {"usage": 0, "cost": None},
    }


def test_repeated_fall_back_hour_is_the_later_hour():
    hours = heat_hours(
        [
            {
                "entries": [
                    hour("2026-10-25T01:00:00Z", {"value": 1}),
                    hour("2026-10-25T02:00:00Z", {"value": 2}),
                    hour("2026-10-25T02:00:00Z", {"value": 3}),
                    hour("2026-10-25T03:00:00Z", {"value": 4}),
                ]
            }
        ]
    )
    assert [(h.hour, v["usage"]) for h, v in sorted(hours.items())] == [
        (23, 1),
        (0, 2),
        (1, 3),
        (2, 4),
    ]


def test_hours_without_time_of_day_are_refused():
    with pytest.raises(ValueError):
        heat_hours([{"entries": [hour("2026-10-21T00:00:00Z", {"value": 1})] * 2}])
