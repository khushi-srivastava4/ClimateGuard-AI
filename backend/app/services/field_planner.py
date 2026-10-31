"""Forecast-conditioned field checks; recommendations are not prescriptions."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List


def build_field_plan(
    weather: Dict[str, Any],
    crop: str,
    growth_stage: str | None = None,
    irrigation_method: str | None = None,
) -> List[Dict[str, Any]]:
    """Create only actions justified by the available forecast.

    SoilGrids estimates are deliberately not used to infer current field
    moisture. Irrigation actions ask the farmer to inspect field conditions.
    """
    daily = weather.get("daily")
    if not isinstance(daily, list):
        return []

    today = date.today().isoformat()
    actions: List[Dict[str, Any]] = []
    for day in daily:
        if not isinstance(day, dict):
            continue
        forecast_date = day.get("date")
        if not isinstance(forecast_date, str) or forecast_date < today:
            continue

        rain_mm = day.get("precipitation_sum")
        rain_probability = day.get("precipitation_probability_max")
        max_temp = day.get("temperature_2m_max")
        base = {
            "date": forecast_date,
            "crop": crop,
            "growth_stage": growth_stage,
            "irrigation_method": irrigation_method,
            "source": "Open-Meteo forecast",
        }

        if isinstance(rain_mm, (int, float)) and rain_mm >= 20:
            actions.append({
                **base,
                "action": "Inspect field drains and low-lying areas",
                "priority": "high",
                "reason": f"{rain_mm:g} mm of rainfall is forecast; check drainage and standing water.",
                "condition": "Recheck the latest forecast and inspect the field after rainfall.",
                "precaution": "Do not enter flooded fields or operate machinery on saturated soil.",
            })
        elif (
            isinstance(rain_probability, (int, float))
            and rain_probability >= 70
            and isinstance(rain_mm, (int, float))
            and rain_mm >= 10
        ):
            actions.append({
                **base,
                "action": "Monitor drainage before and after forecast rain",
                "priority": "medium",
                "reason": f"Rain probability is {rain_probability}% with {rain_mm:g} mm forecast.",
                "condition": "Update this check if the forecast changes.",
                "precaution": "Avoid irrigation while substantial rainfall is expected.",
            })

        if isinstance(max_temp, (int, float)) and max_temp >= 35:
            actions.append({
                **base,
                "action": "Check crop for heat stress during cooler hours",
                "priority": "high" if max_temp >= 40 else "medium",
                "reason": f"Maximum temperature of {max_temp:g}°C is forecast.",
                "condition": "Observe crop and local conditions; forecast temperature is not a field measurement.",
                "precaution": "Do not apply unverified chemical or fertilizer treatments.",
            })

        if isinstance(rain_mm, (int, float)) and rain_mm < 1 and (
            not isinstance(rain_probability, (int, float)) or rain_probability < 40
        ):
            actions.append({
                **base,
                "action": "Check soil and crop before deciding whether to irrigate",
                "priority": "low",
                "reason": "Little or no rainfall is forecast for this day.",
                "condition": "Irrigate only if field conditions and crop needs indicate it; postpone if the soil is wet or rain becomes likely.",
                "precaution": "This plan has no current soil-moisture measurement and does not prescribe an irrigation amount.",
            })

    return _merge_runs(actions)


_RANK = {"low": 0, "medium": 1, "high": 2}


def _next_day(day: str) -> str | None:
    try:
        return (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    except ValueError:
        return None


def _merge_runs(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse the same action on consecutive days into one entry with an end date.

    Previously a 14-day dry forecast produced 14 identical "check soil and crop" rows; now it is one row for the spell.
    """
    merged: List[Dict[str, Any]] = []
    for act in sorted(actions, key=lambda a: (a["action"], a["date"])):
        prev = merged[-1] if merged else None
        if prev and prev["action"] == act["action"] and _next_day(prev.get("end_date", prev["date"])) == act["date"]:
            prev["end_date"] = act["date"]
            prev["days"] = prev.get("days", 1) + 1
            if _RANK.get(act["priority"], 0) > _RANK.get(prev["priority"], 0):
                prev["priority"] = act["priority"]
        else:
            merged.append(dict(act))
    for act in merged:
        if act.get("days", 1) > 1:
            act["reason"] = f"{act['reason']} Applies for {act['days']} days ({act['date']} to {act['end_date']})."
    return sorted(merged, key=lambda a: (a["date"], -_RANK.get(a["priority"], 0)))
