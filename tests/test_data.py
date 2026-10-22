"""Verify delayed meter data, missing days, corrections and month boundaries."""

from datetime import date

import pytest

from custom_components.eneco.data import heat_days, latest_day, latest_value, period_total


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
