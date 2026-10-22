"""Read measured heat values without confusing missing data with zero usage."""

from datetime import date
from typing import Any

from .api import amount


def heat_days(snapshot: dict[str, Any]) -> dict[date, dict[str, float | None]]:
    """Flatten daily API groups; ignore forecasts and entries without heat data."""
    days = {}
    for group in snapshot["usages"]:
        for entry in group.get("entries", []):
            actual = entry.get("actual") or {}
            warmth = actual.get("warmth")
            if not warmth or warmth.get("status") != "MEASURED":
                continue
            day = date.fromisoformat(actual["date"][:10])
            high, low = amount(warmth.get("high")), amount(warmth.get("low"))
            days[day] = {
                "usage": None if high is None and low is None else (high or 0) + (low or 0),
                "cost": amount(warmth.get("totalCostInclVat")),
            }
    return days


def period_total(
    snapshot: dict[str, Any], today: date, field: str, previous: bool = False
) -> float | None:
    """Sum reported days only, with no fabricated zero for an empty period."""
    year, month = today.year, today.month
    if previous:
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    values = [
        v[field]
        for d, v in heat_days(snapshot).items()
        if (d.year, d.month) == (year, month) and d <= today and v[field] is not None
    ]
    return sum(values) if values else None


def latest_day(snapshot: dict[str, Any]) -> date | None:
    """Return the date of the most recent measurement."""
    return max(heat_days(snapshot), default=None)


def latest_value(snapshot: dict[str, Any], field: str) -> float | None:
    """Read the latest reported day, which need not be yesterday."""
    day = latest_day(snapshot)
    return heat_days(snapshot)[day][field] if day is not None else None
