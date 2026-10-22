"""Read measured heat values without confusing missing data with zero usage."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .api import amount

# Eneco labels readings with Dutch wall-clock time and a misleading "Z" suffix.
ENECO_TZ = ZoneInfo("Europe/Amsterdam")


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
                "usage_cost": amount(warmth.get("totalUsageCostInclVat")),
                "fixed": amount(warmth.get("fixedCostInclVat")),
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


def heat_hours(usages: list[dict[str, Any]]) -> dict[datetime, dict[str, float | None]]:
    """Measured hours keyed by their UTC start, from one hourly API response.

    The hour after a daylight-saving fall-back repeats its wall-clock label; the
    second occurrence is the later hour. Any other repeated label is an error, so a
    response without hours in its labels is never imported as one hour.
    """
    hours: dict[datetime, dict[str, float | None]] = {}
    seen: set[datetime] = set()
    for group in usages:
        for entry in group.get("entries", []):
            actual = entry.get("actual") or {}
            warmth = actual.get("warmth")
            if not warmth or warmth.get("status") != "MEASURED":
                continue
            local = datetime.fromisoformat(actual["date"].removesuffix("Z"))
            if local in seen and not _ambiguous(local):
                raise ValueError(f"Eneco repeated the hour {local.isoformat()}")
            start = local.replace(tzinfo=ENECO_TZ, fold=int(local in seen)).astimezone(UTC)
            seen.add(local)
            high, low = amount(warmth.get("high")), amount(warmth.get("low"))
            if high is None and low is None:
                continue
            hours[start] = {
                "usage": (high or 0) + (low or 0),
                "cost": amount(warmth.get("totalUsageCostInclVat")),
                "fixed": amount(warmth.get("fixedCostInclVat")),
            }
    return hours


def _ambiguous(local: datetime) -> bool:
    early = local.replace(tzinfo=ENECO_TZ, fold=0)
    late = local.replace(tzinfo=ENECO_TZ, fold=1)
    return early.utcoffset() != late.utcoffset()


def hours_in_day(day: date) -> int:
    """23, 24 or 25: the length of a Dutch calendar day."""
    length = local_midnight(day + timedelta(days=1)) - local_midnight(day)
    return round(length.total_seconds() / 3600)


def local_midnight(day: date) -> datetime:
    """The UTC start of a Dutch calendar day."""
    return datetime.combine(day, datetime.min.time(), ENECO_TZ).astimezone(UTC)
