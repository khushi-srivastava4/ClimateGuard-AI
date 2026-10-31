"""Soil property service using ISRIC SoilGrids.

Fixes "Soil data response contained no usable property values":
* SoilGrids returns null for many pixels (built-up land, water, field edges). We now read two depths and, if the pixel
  is empty, try two neighbouring pixels (about 250 m away) before giving up.
* The old code asked for one depth only and used the 8 s provider timeout, so slow replies became errors.
Values are modelled estimates, not live soil-moisture measurements.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import httpx

from app.config import settings
from app.models.soil import SoilData
from app.utils.cache import cache
from app.utils.http import slow_provider_timeout

logger = logging.getLogger(__name__)

URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
PROPERTIES = ["sand", "clay", "silt", "soc", "phh2o", "bdod"]
DEPTHS = ["0-5cm", "5-15cm"]
NEIGHBOUR_OFFSETS = [(0.0, 0.0), (0.0025, 0.0), (-0.0025, 0.0)]
SOIL_TTL_SECONDS = 7 * 24 * 3600     # soil does not change; also protects SoilGrids' rate limit


def _parse(payload: object) -> Tuple[Dict[str, float], Dict[str, str]]:
    values: Dict[str, float] = {}
    units: Dict[str, str] = {}
    layers = ((payload or {}).get("properties") or {}).get("layers") or [] if isinstance(payload, dict) else []
    for layer in layers:
        if not isinstance(layer, dict) or not layer.get("name"):
            continue
        measure = layer.get("unit_measure") if isinstance(layer.get("unit_measure"), dict) else {}
        factor = measure.get("d_factor") or 1
        means = []
        for depth in layer.get("depths") or []:
            mean = ((depth or {}).get("values") or {}).get("mean") if isinstance(depth, dict) else None
            if isinstance(mean, (int, float)) and not isinstance(mean, bool):
                means.append(float(mean))
        if means:
            name = str(layer["name"])
            values[name] = round(sum(means) / len(means) / factor, 3)
            units[name] = str(measure.get("target_units") or measure.get("mapped_units") or "")
    return values, units


async def _query(client: httpx.AsyncClient, latitude: float, longitude: float):
    response = await client.get(
        URL,
        params={
            "lon": round(longitude, 5),
            "lat": round(latitude, 5),
            "property": PROPERTIES,
            "depth": DEPTHS,
            "value": "mean",
        },
    )
    response.raise_for_status()
    return _parse(response.json())


async def get_soil(latitude: float, longitude: float) -> SoilData:
    key = f"soil2:{round(latitude, 4)}:{round(longitude, 4)}"
    cached = cache.get(key)
    if cached:
        data = SoilData(**cached)
        if data.properties:
            return data
        cache.delete(key)

    note: Optional[str] = None
    try:
        async with httpx.AsyncClient(timeout=slow_provider_timeout()) as client:
            for step, (dlat, dlon) in enumerate(NEIGHBOUR_OFFSETS):
                values, units = await _query(client, latitude + dlat, longitude + dlon)
                if values:
                    if step:
                        note = "Pixel at the exact point was empty; values are from a neighbouring pixel about 250 m away."
                    soil = SoilData(
                        latitude=latitude,
                        longitude=longitude,
                        properties=values,
                        property_units=units,
                        depth="0-15cm (mean of 0-5 and 5-15 cm)",
                        retrieved_at=datetime.now(timezone.utc),
                        error=note,
                    )
                    cache.set(key, soil.model_dump(mode="json"), ttl_seconds=SOIL_TTL_SECONDS)
                    return soil
        error = "SoilGrids has no soil values for this location or its immediate surroundings (built-up land or water)."
    except httpx.TimeoutException:
        error = "Soil data unavailable (SoilGrids did not answer in time). Try again in a minute."
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        error = (
            "Soil data unavailable (SoilGrids rate limit reached; try again in a minute)."
            if status == 429 else f"Soil data unavailable (SoilGrids returned HTTP {status})."
        )
    except Exception as exc:
        logger.warning("Soil lookup failed (%s).", type(exc).__name__)
        error = f"Soil data unavailable ({type(exc).__name__})."
    return SoilData(latitude=latitude, longitude=longitude, error=error)
