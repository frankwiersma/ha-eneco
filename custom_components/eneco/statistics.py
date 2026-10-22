"""Import measured heat hours as long-term statistics for the Energy dashboard."""

from datetime import date, datetime, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .api import EnecoClient
from .const import DOMAIN
from .data import ENECO_TZ, heat_hours

CHUNK = timedelta(days=7)
# Eneco can still fill in or correct hours of the days before its latest reading.
REVISE = timedelta(days=3)
MAX_BACKFILL_CHUNKS = 104


class EnecoStatistics:
    """Keep the heat and heat-cost statistics in step with Eneco's hourly readings."""

    def __init__(
        self, hass: HomeAssistant, client: EnecoClient, customer_id: int, account_id: int
    ) -> None:
        self.hass = hass
        self.client = client
        self.customer_id = customer_id
        self.account_id = account_id
        prefix = f"{DOMAIN}:heat_{customer_id}_{account_id}"
        self.heat = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name="Eneco heat",
            source=DOMAIN,
            statistic_id=prefix,
            unit_class=EnergyConverter.UNIT_CLASS,
            unit_of_measurement=UnitOfEnergy.GIGA_JOULE,
        )
        self.cost = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name="Eneco heat cost",
            source=DOMAIN,
            statistic_id=f"{prefix}_cost",
            unit_class=None,
            unit_of_measurement="EUR",
        )

    async def async_update(self, today: date) -> None:
        """Import new hours and rewrite the recent ones that Eneco may have corrected."""
        heat_id = self.heat["statistic_id"]
        last = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, heat_id, True, set()
        )
        if last:
            last_day = dt_util.utc_from_timestamp(last[heat_id][0]["start"]).astimezone(ENECO_TZ)
            hours = await self._fetch(last_day.date() - REVISE, today + timedelta(days=1))
        else:
            hours = await self._backfill(today)
        if not hours:
            return
        start = min(hours)
        for metadata, field in ((self.heat, "usage"), (self.cost, "cost")):
            total = await self._sum_before(metadata["statistic_id"], start)
            rows = []
            for hour in sorted(hours):
                value = hours[hour][field]
                if value is None:
                    continue
                total += value
                rows.append(StatisticData(start=hour, state=value, sum=total))
            if rows:
                async_add_external_statistics(self.hass, metadata, rows)

    async def _fetch(self, first: date, end: date) -> dict[datetime, dict[str, float | None]]:
        hours: dict[datetime, dict[str, float | None]] = {}
        while first < end:
            last = min(first + CHUNK, end)
            hours |= heat_hours(
                await self.client.hours(self.customer_id, self.account_id, first, last)
            )
            first = last
        return hours

    async def _backfill(self, today: date) -> dict[datetime, dict[str, float | None]]:
        """Walk back a week at a time until a week without readings precedes the data."""
        hours: dict[datetime, dict[str, float | None]] = {}
        end = today + timedelta(days=1)
        for _ in range(MAX_BACKFILL_CHUNKS):
            week = await self._fetch(end - CHUNK, end)
            if not week and hours:
                break
            hours |= week
            end -= CHUNK
        return hours

    async def _sum_before(self, statistic_id: str, start: datetime) -> float:
        """The running total just before start, whatever rows will be rewritten."""
        recorder = get_instance(self.hass)
        rows = await recorder.async_add_executor_job(
            statistics_during_period,
            self.hass,
            start,
            None,
            {statistic_id},
            "hour",
            None,
            {"sum", "change"},
        )
        if rows.get(statistic_id):
            first = rows[statistic_id][0]
            return first["sum"] - first["change"]
        last = await recorder.async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )
        return last[statistic_id][0]["sum"] if last else 0.0
