"""Drought indicator for the /advise graph: modelled soil moisture + crop water demand + 30-year rainfall normals."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from app.services import climate_risk as R
from app.services import live_data as L
from app.services.crop_profiles import CROPS


async def drought_indicator(lat: float, lon: float, crop: str, soil_props: Optional[Dict[str, float]] = None,
                            stage: Optional[str] = None) -> Dict[str, Any]:
    profile = CROPS.get((crop or "wheat").strip().lower()) or CROPS["wheat"]
    fc, clim = await asyncio.gather(L.forecast(lat, lon), L.climatology(lat, lon), return_exceptions=True)
    if isinstance(fc, Exception):
        raise fc
    clay = (soil_props or {}).get("clay")
    soil = {"clay_pct": clay} if isinstance(clay, (int, float)) and clay >= 1 else None
    a = R.assess(fc, None, None if isinstance(clim, Exception) else clim, soil, profile, stage)
    d = a["risks"]["drought"]
    return {"score": d["score"], "level": d["level"], "evidence": [e["text"] for e in d["evidence"]],
            "irrigation_mm_week": a["water"]["weekly_irrigation_mm"], "normals_used": not isinstance(clim, Exception),
            "soil_texture_assumed": a["soil_model"]["texture_assumed"]}
