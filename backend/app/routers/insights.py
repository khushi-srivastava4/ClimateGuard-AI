"""New endpoints. Register with: app.include_router(insights_router)   (see INTEGRATION.md)"""
import asyncio
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from ..services import live_data as L, climate_risk as R, soil_live, mandi_live, satellite_service
from ..services import action_planner, alert_engine, advisory_service
from ..services.crop_profiles import CROPS
from ..services.live_data import SourceError

router = APIRouter(tags=["insights"])
SRC_NAMES = {"S1": "open-meteo/forecast", "S2": "open-meteo/flood", "S3": "nasa-power", "S4": "soilgrids", "S5": "noaa-cpc/oni", "S6": "data.gov.in/agmarknet"}


def _crop(c):
    if c not in CROPS:
        raise HTTPException(422, f"unknown crop '{c}'. Use one of: {', '.join(CROPS)}")
    return CROPS[c]


async def build(lat, lon, crop_id, stage=None, soil_type=None, state=None, with_market=True):
    crop = _crop(crop_id)
    keys = ["fc", "flood", "clim", "soil", "enso"]
    res = await asyncio.gather(L.forecast(lat, lon), L.flood(lat, lon), L.climatology(lat, lon),
                               soil_live.get_soil(lat, lon, soil_type), L.enso(), return_exceptions=True)
    d, warnings = dict(zip(keys, res)), []
    for k, v in d.items():
        if isinstance(v, Exception):
            warnings.append(f"{k} unavailable: {v}")
            d[k] = None
    if d["fc"] is None:
        raise HTTPException(503, "Forecast source (Open-Meteo) is unavailable, so no assessment can be made. " + "; ".join(warnings))
    a = R.assess(d["fc"], d["flood"], d["clim"], d["soil"], crop, stage)
    a["actions_v2"] = action_planner.plan_actions(a, crop_id, stage)
    mandi = None
    if with_market and state:
        try:
            mandi = await mandi_live.get_mandi(state, crop["mandi"])
        except SourceError as e:
            warnings.append(f"market unavailable: {e.msg}")
    elif with_market:
        warnings.append("market skipped: no state given")
    a.update({"soil": d["soil"], "enso": d["enso"], "market": mandi, "warnings": warnings,
              "sources": {sid: L.STATUS.get(n, {"state": "not-called"}) for sid, n in SRC_NAMES.items()}})
    return a


@router.get("/insights/risk")
async def risk(lat: float = Query(..., ge=-60, le=70), lon: float = Query(..., ge=-180, le=180), crop: str = "wheat",
               stage: str | None = None, soil_type: str | None = None, state: str | None = None):
    return await build(lat, lon, crop, stage, soil_type, state)


@router.get("/insights/grid")
async def grid(lat: float = Query(..., ge=-60, le=70), lon: float = Query(..., ge=-180, le=180),
               span_km: float = Query(40, ge=5, le=200), n: int = Query(5, ge=2, le=7)):
    step = span_km / (n - 1)
    pts = [(lat + (i - (n - 1) / 2) * step / 111.32, lon + (j - (n - 1) / 2) * step / (111.32 * max(0.2, __import__("math").cos(__import__("math").radians(lat)))))
           for i in range(n) for j in range(n)]
    try:
        data = await L.grid_forecast(pts)
    except SourceError as e:
        raise HTTPException(503, str(e))
    cells = [{"lat": round(p[0], 4), "lon": round(p[1], 4), **R.grid_scores(x["daily"])} for p, x in zip(pts, data) if x.get("daily")]
    return {"cells": cells, "cell_km": round(step, 1), "horizon_days": 7, "note": "Crop-agnostic 7-day hazard index per cell from Open-Meteo."}


@router.get("/satellite/ndvi")
async def ndvi(lat: float = Query(..., ge=-60, le=70), lon: float = Query(..., ge=-180, le=180),
               days: int = Query(60, ge=10, le=180), half_km: float = Query(0.5, ge=0.1, le=5)):
    try:
        return await satellite_service.ndvi_series(lat, lon, days, half_km)
    except SourceError as e:
        raise HTTPException(503, str(e))
    except ImportError:
        raise HTTPException(501, "Install satellite dependencies: pip install rasterio numpy")


class AdviseV2(BaseModel):
    lat: float = Field(ge=-60, le=70)
    lon: float = Field(ge=-180, le=180)
    crop: str = "wheat"
    stage: str | None = None
    soil_type: str | None = None
    state: str | None = None
    language: str = "en"
    question: str | None = None
    farm_id: int | None = None
    alert_threshold: int = 60


@router.post("/advise/v2")
async def advise_v2(req: AdviseV2):
    a = await build(req.lat, req.lon, req.crop, req.stage, req.soil_type, req.state)
    summary = advisory_service.build_summary(a, req.crop, req.stage, a["soil"], a["enso"], a["market"],
                                             {"state": req.state}, a["actions_v2"])
    out = await advisory_service.advise(summary, req.language, req.question)
    out["alerts"] = alert_engine.build_alerts(req.farm_id, a, True, req.alert_threshold)
    out["assessment"] = {k: a[k] for k in ("risks", "water", "sowing_windows", "dry_windows", "actions_v2", "soil", "enso", "market", "warnings", "sources", "series")}
    return out
