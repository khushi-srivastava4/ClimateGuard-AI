"""Deterministic agronomic risk engine used by the /advise graph.

Scores are heuristic indicators on a 0-100 scale. They are NOT statistically calibrated probabilities of crop loss,
and an indicator whose inputs are missing is reported as None (never as 0).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.models.risk import RiskReport
from app.services.crop_profiles import CROPS

HEAT_ONSET_C = 28.0        # stress starts to accumulate here
HEAT_POINTS_PER_C = 7.25   # 36 C -> 58, saturates near 41.8 C
RAIN_POINTS_PER_MM = 2.5   # total forecast rain: 10 mm -> 25, saturates at 40 mm
HEAVY_DAY_MM = 115.6       # IMD "very heavy rainfall" lower bound for a single day


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _clamp(value: float) -> int:
    return int(round(max(0.0, min(100.0, value))))


def _stamp(value: Any) -> str:
    """'2026-10-31T00:00:00+00:00' -> ' (retrieved 2026-10-31T00:00Z)'; empty when unknown."""
    if not isinstance(value, str) or len(value) < 16:
        return ""
    return f" (retrieved {value[:16]}Z)"


def _daily_values(weather: Dict[str, Any], key: str) -> List[float]:
    daily = weather.get("daily")
    if not isinstance(daily, list):
        return []
    out = []
    for day in daily:
        value = _num(day.get(key)) if isinstance(day, dict) else None
        if value is not None:
            out.append(value)
    return out


def _category(score: Optional[int]) -> Optional[str]:
    if score is None:
        return None
    return "high" if score >= 75 else "moderate" if score >= 40 else "low"


def compute_risk(
    weather: Dict[str, Any],
    soil: Dict[str, Any],
    mandi: Dict[str, Any],
    crop: str = "wheat",
) -> RiskReport:
    weather = weather if isinstance(weather, dict) else {}
    soil = soil if isinstance(soil, dict) else {}
    mandi = mandi if isinstance(mandi, dict) else {}
    profile = CROPS.get((crop or "wheat").strip().lower())

    reasons: List[str] = []
    sources: List[str] = []
    quality: List[str] = [
        "Risk scores are heuristic indicators, not statistically calibrated probabilities of crop loss."
    ]

    # --- heat wave (forecast maximum temperature)
    max_temp = _num(weather.get("max_temp"))
    heat = None
    if max_temp is not None:
        heat = _clamp((max_temp - HEAT_ONSET_C) * HEAT_POINTS_PER_C)
        reasons.append(f"Heat-wave risk: forecast maximum temperature is {max_temp:g}\u00b0C.")

    # --- heavy rain / flood (total forecast rain, raised by the heaviest single day when daily values exist)
    rain_total = _num(weather.get("precipitation_total"))
    day_rain = _daily_values(weather, "precipitation_sum")
    flood = None
    if rain_total is not None:
        flood = _clamp(rain_total * RAIN_POINTS_PER_MM)
        reasons.append(f"Flood risk: {rain_total:g} mm of rain is forecast over the period.")
    if day_rain:
        peak_day = max(day_rain)
        by_day = _clamp(peak_day / HEAVY_DAY_MM * 100)
        if flood is None or by_day > flood:
            flood = by_day
            reasons.append(f"Flood risk: heaviest forecast day is {peak_day:g} mm.")
    if heat is not None or flood is not None:
        sources.append(f"Open-Meteo forecast{_stamp(weather.get('retrieved_at'))}: max_temp, precipitation_total")

    # --- waterlogging (needs a daily rainfall series; soil drainage is not measured)
    water_logging = None
    if len(day_rain) >= 3:
        peak3 = max(sum(day_rain[i:i + 3]) for i in range(len(day_rain) - 2))
        limit = float(profile["waterlog"]) if profile else 60.0
        props = soil.get("properties") if isinstance(soil.get("properties"), dict) else {}
        clay = _num(props.get("clay"))
        if clay is not None and clay >= 1:          # SoilGrids clay as % ; heavier soils drain slower
            limit *= max(0.5, 1.2 - clay / 100)
        water_logging = _clamp(peak3 / (1.25 * limit) * 100)
        reasons.append(
            f"Waterlogging risk: wettest 3-day spell is {peak3:g} mm against about {limit:g} mm that this crop tolerates."
        )
        quality.append("Waterlogging uses forecast rainfall only; soil drainage and current soil moisture are not measured.")
    else:
        quality.append("Waterlogging indicator unavailable: a daily rainfall forecast is required.")

    # --- drought is never inferred from a rain forecast alone
    drought = None
    quality.append(
        "Drought indicator unavailable here: it needs soil-moisture and evapotranspiration data (see /insights/risk)."
    )

    # --- soil provenance
    props = soil.get("properties")
    if isinstance(props, dict) and props:
        sources.append(f"ISRIC SoilGrids{_stamp(soil.get('retrieved_at'))}: {', '.join(sorted(props))}")
        quality.append("SoilGrids soil properties are modelled estimates, not current field-moisture measurements.")
    else:
        detail = soil.get("error") or "no soil properties were returned"
        quality.append(f"Soil estimates unavailable: {detail}")

    # --- market provenance
    if mandi.get("error"):
        quality.append(f"Market data unavailable: {mandi['error']}")
    elif _num(mandi.get("average_price")) is not None:
        reasons.append(f"Mandi price: average \u20b9{mandi['average_price']:g}/quintal for {crop}.")
        sources.append(f"{mandi.get('source') or 'Agmarknet'}{_stamp(mandi.get('retrieved_at'))}: modal_price")

    scored = [s for s in (heat, flood, water_logging, drought) if s is not None]
    overall = max(scored) if scored else None

    period = None
    dates = sorted(d["date"] for d in weather.get("daily", []) if isinstance(d, dict) and isinstance(d.get("date"), str) and d["date"])
    if dates:
        period = f"Forecast {dates[0]} to {dates[-1]}"
    if overall is None:
        quality.append("No risk could be scored because forecast values are unavailable.")

    return RiskReport(
        heat_wave=heat,
        flood=flood,
        water_logging=water_logging,
        drought=drought,
        overall=overall,
        category=_category(overall),
        reasons=reasons,
        sources=sources,
        data_quality=quality,
        assessment_period=period,
    )
