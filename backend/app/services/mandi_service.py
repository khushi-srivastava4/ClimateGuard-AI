"""Mandi price service using the Data.gov.in Agmarknet daily-price resource.

Fixes "Market data unavailable (ReadTimeout)":
* data.gov.in often needs 10-25 s; the shared 8 s read cap made every call fail (now slow_provider_timeout()).
* The old request sent latitude/longitude/criteria, which the resource does not filter on. It now filters on
  commodity (and state / district when known) and widens to the whole country if the state has no record today.
* Successful responses are kept for 30 days; if the portal is down, the last real prices are returned with a clear
  warning in `error`. No price is ever invented.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, List, Optional

from app.config import settings
from app.models.mandi import MandiData, MandiPricePoint
from app.services.crop_profiles import CROPS
from app.services.live_data import SourceError, fetch, validate_mandi_payload
from app.utils.cache import cache
from app.utils.http import slow_provider_timeout

logger = logging.getLogger(__name__)
API_URL = "https://api.data.gov.in/resource/"
STALE_TTL_SECONDS = 30 * 24 * 3600


def _iso(day: str) -> str:
    """Agmarknet dates are dd/mm/yyyy; return yyyy-mm-dd so dates sort correctly."""
    try:
        return datetime.strptime(day.strip(), "%d/%m/%Y").date().isoformat()
    except (ValueError, AttributeError):
        return day or ""


def _commodity(crop: str) -> str:
    profile = CROPS.get((crop or "").strip().lower())
    return profile["mandi"] if profile else (crop or "Wheat").strip().title()


def _points(records: List[Dict[str, Any]], commodity: str) -> List[MandiPricePoint]:
    rows = []
    for rec in records:
        try:
            price = float(str(rec.get("modal_price")).replace(",", ""))
        except (TypeError, ValueError):
            continue
        rows.append((_iso(str(rec.get("arrival_date", ""))), str(rec.get("market") or "Unknown"), price))
    dates = sorted({r[0] for r in rows})
    if len(dates) > 1:     # a real time series: one median price per day (last 10 days)
        out = []
        for day in dates[-10:]:
            day_prices = [r[2] for r in rows if r[0] == day]
            out.append(MandiPricePoint(date=day, market=f"{len(day_prices)} markets (median)", price=round(median(day_prices), 2), commodity=commodity))
        return out
    top = sorted(rows, key=lambda r: -r[2])[:10]       # one day only: compare markets instead
    return [MandiPricePoint(date=r[0], market=r[1], price=r[2], commodity=commodity) for r in top]


async def _fetch(commodity: str, state: Optional[str], district: Optional[str]) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {
        "api-key": settings.MANDI_API_KEY,
        "format": "json",
        "limit": 200,
        "filters[commodity]": commodity,
    }
    if state:
        params["filters[state.keyword]"] = state
    if district:
        params["filters[district]"] = district
    payload = await fetch(
        "data.gov.in/agmarknet",
        f"{API_URL}{settings.MANDI_RESOURCE_ID}",
        params,
        ttl=settings.CACHE_TTL,
        retries=2,
        timeout=slow_provider_timeout(),
        validator=validate_mandi_payload,
        stale_if_error=False,
    )
    return payload["records"]


async def get_mandi(
    latitude: float,
    longitude: float,
    crop: str = "wheat",
    mandicriteria: str = "",
    state: Optional[str] = None,
    district: Optional[str] = None,
) -> MandiData:
    commodity = _commodity(crop)
    if not settings.MANDI_API_KEY:
        return MandiData(crop=crop, market="N/A", error="Mandi data unavailable: no MANDI_API_KEY configured.")

    key = f"mandi2:{commodity}:{state or '*'}:{district or '*'}"
    fresh = cache.get(key)
    if fresh:
        return MandiData(**fresh)
    stale_key = f"mandi2-stale:{commodity}:{state or '*'}:{district or '*'}"

    error: Optional[str] = None
    try:
        # most specific first, then widen: district+state -> state -> whole country
        attempts = [(state, district)] if (state and district) else []
        attempts += [(state, None)] if state else []
        attempts += [(None, None)]
        for st, dist in attempts:
            records = await _fetch(commodity, st, dist)
            points = _points(records, commodity) if records else []
            if points:
                scope = ", ".join(x for x in (dist, st) if x) or "India (no records for the selected state today)"
                data = MandiData(
                    crop=crop, market=scope, prices=points, source="Agmarknet (data.gov.in)",
                    retrieved_at=datetime.now(timezone.utc),
                )
                dump = data.model_dump(mode="json")
                cache.set(key, dump, ttl_seconds=settings.CACHE_TTL)
                cache.set(stale_key, dump, ttl_seconds=STALE_TTL_SECONDS)
                return data
        error = f"No current mandi prices were published for {commodity}."
    except SourceError as exc:
        error = exc.msg
    except Exception as exc:
        logger.warning("Mandi lookup failed (%s).", type(exc).__name__)
        error = f"Mandi request failed ({type(exc).__name__})."

    old = cache.get(stale_key)
    if old:
        data = MandiData(**old)
        when = data.retrieved_at.strftime("%Y-%m-%d %H:%M UTC") if data.retrieved_at else "an earlier request"
        data.error = f"Live request failed ({error}) Showing the last real prices retrieved on {when}."
        return data
    return MandiData(crop=crop, market="N/A", error=f"Market data unavailable: {error}")
