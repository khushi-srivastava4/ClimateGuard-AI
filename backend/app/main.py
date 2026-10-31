"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import date, timedelta
from enum import Enum
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse, Response

from app.agent.graph import build_graph
from app.config import settings
from app.models.mandi import MandiData, MandiPricePoint
from app.models.risk import RiskReport
from app.models.soil import SoilData
from app.models.weather import WeatherData
from app.routers.ops import router as ops_router
from app.persistence import (
    ActionStatus,
    FarmUpdate,
    InvalidTransitionError,
    NotFoundError,
    PersistenceValidationError,
    create_action_item,
    create_alert,
    create_farm,
    delete_farm,
    get_farm,
    list_action_items,
    list_alerts,
    list_farms,
    mark_alert_read,
    update_action_status,
    update_farm,
)
from app.routers.insights import router as insights_router
from app.routers.voice import router as voice_router
from app.services.field_planner import build_field_plan

logger = logging.getLogger(__name__)


class AdvisoryRequest(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    farm_id: str | None = None
    language: Literal["en", "hi"] = "en"
    crop: str = Field(default="wheat", min_length=1, max_length=80)
    mandicriteria: str = "price"
    market_state: str | None = Field(default=None, max_length=100)
    market_district: str | None = Field(default=None, max_length=100)


class AdvisoryLocation(BaseModel):
    latitude: float
    longitude: float


class AdvisoryResponse(BaseModel):
    advice: str
    advice_status: Literal["generated", "fallback", "unavailable"]
    advice_provider: str | None = None
    risk: RiskReport
    sources: list[str]
    mandi: list[MandiPricePoint]
    weather: WeatherData
    soil: SoilData
    market: MandiData
    field_plan: list[dict[str, Any]]
    farm: dict[str, Any] | None
    location: AdvisoryLocation


class FarmInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    location: str = Field(min_length=1, max_length=240)
    state: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    crop: str | None = Field(default=None, max_length=80)
    area_hectares: float | None = Field(default=None, gt=0)
    variety: str | None = Field(default=None, max_length=120)
    growth_stage: str | None = Field(default=None, max_length=120)
    sowing_date: str | None = None
    soil_type: str | None = Field(default=None, max_length=120)
    irrigation_method: str | None = Field(default=None, max_length=120)
    farming_preferences: dict[str, Any] = Field(default_factory=dict)


class FarmPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    location: str | None = Field(default=None, min_length=1, max_length=240)
    state: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    crop: str | None = Field(default=None, max_length=80)
    area_hectares: float | None = Field(default=None, gt=0)
    variety: str | None = Field(default=None, max_length=120)
    growth_stage: str | None = Field(default=None, max_length=120)
    sowing_date: str | None = None
    soil_type: str | None = Field(default=None, max_length=120)
    irrigation_method: str | None = Field(default=None, max_length=120)
    farming_preferences: dict[str, Any] | None = None


class ActionStatusInput(BaseModel):
    status: ActionStatus


class AlertReadInput(BaseModel):
    is_read: bool = True


class AlertPreference(BaseModel):
    enabled: bool = True
    threshold: int = Field(default=70, ge=1, le=100)


app = FastAPI(title="ClimateGuard AI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(insights_router)   # /insights/risk, /insights/grid, /satellite/ndvi, /advise/v2
app.include_router(ops_router)
app.include_router(voice_router)
    
@app.exception_handler(NotFoundError)
async def not_found_handler(_request: Request, error: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(error)})


@app.exception_handler(PersistenceValidationError)
async def persistence_validation_handler(
    _request: Request, error: PersistenceValidationError
) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(error)})


@app.exception_handler(InvalidTransitionError)
async def invalid_transition_handler(
    _request: Request, error: InvalidTransitionError
) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(error)})


def _serialize(record: Any) -> dict[str, Any]:
    result = asdict(record)
    for key, value in result.items():
        if isinstance(value, Enum):
            result[key] = value.value
    return result


def _persist_field_plan(farm_id: str, plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stored = list_action_items(farm_id)
    known = {(item.title, item.due_date) for item in stored}
    for action in plan:
        title = action.get("action")
        due_date = action.get("date")
        if isinstance(title, str) and (title, due_date) not in known:
            stored.append(
                create_action_item(
                    farm_id,
                    title,
                    description=str(action.get("reason", "")),
                    due_date=due_date,
                )
            )
            known.add((title, due_date))
    # Only show actions that are still relevant; old past-dated pending items otherwise pile up forever.
    today = date.today().isoformat()
    return [
        _serialize(item) for item in stored
        if item.due_date is None or item.due_date >= today
    ]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.APP_NAME}


@app.get("/farms")
def farms() -> list[dict[str, Any]]:
    return [_serialize(farm) for farm in list_farms()]


@app.post("/farms", status_code=201)
def add_farm(payload: FarmInput) -> dict[str, Any]:
    return _serialize(create_farm(**payload.model_dump()))


@app.get("/farms/{farm_id}")
def farm_details(farm_id: str) -> dict[str, Any]:
    return _serialize(get_farm(farm_id))


@app.patch("/farms/{farm_id}")
def edit_farm(farm_id: str, payload: FarmPatch) -> dict[str, Any]:
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status_code=422, detail="At least one farm field is required.")
    return _serialize(update_farm(farm_id, FarmUpdate(**values)))


@app.delete("/farms/{farm_id}", status_code=204)
def remove_farm(farm_id: str) -> Response:
    delete_farm(farm_id)
    return Response(status_code=204)


@app.get("/farms/{farm_id}/actions")
def farm_actions(farm_id: str) -> list[dict[str, Any]]:
    get_farm(farm_id)
    return [_serialize(item) for item in list_action_items(farm_id)]


@app.patch("/actions/{action_id}")
def set_action_status(action_id: str, payload: ActionStatusInput) -> dict[str, Any]:
    return _serialize(update_action_status(action_id, payload.status))


@app.get("/alerts")
def alerts(
    farm_id: str | None = None,
    unread_only: bool = False,
) -> list[dict[str, Any]]:
    if farm_id is not None:
        get_farm(farm_id)
    return [_serialize(alert) for alert in list_alerts(farm_id, unread_only=unread_only)]


@app.patch("/alerts/{alert_id}")
def set_alert_read(alert_id: str, payload: AlertReadInput) -> dict[str, Any]:
    return _serialize(mark_alert_read(alert_id, payload.is_read))


@app.get("/farms/{farm_id}/alert-preferences")
def get_alert_preferences(farm_id: str) -> dict[str, Any]:
    farm = get_farm(farm_id)
    preferences = farm.farming_preferences.get("risk_alerts", {})
    return preferences if isinstance(preferences, dict) else {"enabled": True, "threshold": 70}


@app.put("/farms/{farm_id}/alert-preferences")
def update_alert_preferences(farm_id: str, payload: AlertPreference) -> dict[str, Any]:
    farm = get_farm(farm_id)
    preferences = dict(farm.farming_preferences)
    preferences["risk_alerts"] = payload.model_dump()
    updated = update_farm(
        farm_id,
        FarmUpdate(farming_preferences=preferences),
    )
    return updated.farming_preferences["risk_alerts"]


@app.post("/advise", response_model=AdvisoryResponse)
async def advise(payload: AdvisoryRequest) -> dict[str, Any]:
    farm = get_farm(payload.farm_id) if payload.farm_id else None
    farm_has_any_coordinates = farm and (
        farm.latitude is not None or farm.longitude is not None
    )
    farm_has_coordinates = farm and (
        farm.latitude is not None and farm.longitude is not None
    )
    if farm_has_any_coordinates and not farm_has_coordinates:
        raise HTTPException(
            status_code=422,
            detail="The selected farm has incomplete saved coordinates; update its profile.",
        )
    if farm_has_coordinates:
        latitude, longitude = farm.latitude, farm.longitude
    else:
        latitude, longitude = payload.latitude, payload.longitude
    if latitude is None or longitude is None:
        raise HTTPException(
            status_code=422,
            detail="Provide latitude and longitude, or select a farm with saved coordinates.",
        )
    crop = farm.crop if farm and farm.crop else payload.crop

    graph = build_graph()
    state = {
        "latitude": latitude,
        "longitude": longitude,
        "language": payload.language,
        "crop": crop,
        "mandicriteria": payload.mandicriteria,
        "market_state": payload.market_state or (farm.state if farm else None),
        "market_district": payload.market_district or (farm.district if farm else None),
    }
    try:
        result = await asyncio.wait_for(
            graph.ainvoke(state),
            timeout=settings.ADVISE_TIMEOUT,
        )
    except TimeoutError as error:
        logger.error("Advisory graph exceeded its %.1f second deadline.", settings.ADVISE_TIMEOUT)
        raise HTTPException(
            status_code=504,
            detail="Advisory request timed out. Retry in a moment.",
        ) from error
    risk = result.get("risk", {})
    mandi = result.get("mandi", {})
    prices = mandi.get("prices", []) if isinstance(mandi, dict) else []
    weather = result.get("weather", {})
    if not isinstance(weather, dict):
        weather = {}
    weather = {
        **weather,
        "latitude": latitude,
        "longitude": longitude,
        "timezone": weather.get("timezone") or "UTC",
        "daily": weather.get("daily") if isinstance(weather.get("daily"), list) else [],
    }
    soil = result.get("soil", {})
    if not isinstance(soil, dict):
        soil = {}
    soil = {
        **soil,
        "latitude": latitude,
        "longitude": longitude,
        "properties": soil.get("properties") if isinstance(soil.get("properties"), dict) else {},
        "property_units": soil.get("property_units") if isinstance(soil.get("property_units"), dict) else {},
    }
    market = dict(mandi) if isinstance(mandi, dict) else {}
    market.setdefault("crop", crop)
    if not isinstance(market.get("prices"), list):
        market["prices"] = []
    if not isinstance(risk, dict):
        risk = {}
    sources = result.get("sources", risk.get("sources", []))
    if not isinstance(sources, list):
        sources = []
    field_plan = build_field_plan(
        weather,
        crop=crop,
        growth_stage=farm.growth_stage if farm else None,
        irrigation_method=farm.irrigation_method if farm else None,
    )
    actions = (
        _persist_field_plan(farm.id, field_plan)
        if farm
        else field_plan
    )
    alert_preference = (
        farm.farming_preferences.get("risk_alerts", {}) if farm else {}
    )
    if not isinstance(alert_preference, dict):
        alert_preference = {}
    threshold = alert_preference.get("threshold", 70)
    if (
        farm
        and alert_preference.get("enabled", True)
        and isinstance(threshold, int)
        and not isinstance(threshold, bool)
        and isinstance(risk, dict)
        and isinstance(risk.get("overall"), int)
        and risk["overall"] >= threshold
    ):
        create_alert(
            farm.id,
            "high_risk",
            f"High overall risk: {risk.get('category') or 'elevated'}",
            "; ".join(risk.get("reasons", []))
            or "The latest available risk assessment crossed the configured threshold.",
            dedupe_key=f"overall:{risk['overall']}",
            cooldown=timedelta(hours=6),
        )
    return {
        "advice": result.get("advice", "AI-generated advisory is unavailable."),
        "advice_status": result.get("advice_status", "unavailable"),
        "advice_provider": result.get("advice_provider"),
        "risk": risk,
        "sources": sources,
        "mandi": prices,
        "weather": weather,
        "soil": soil,
        "market": market,
        "field_plan": actions,
        "farm": _serialize(farm) if farm else None,
        "location": {"latitude": latitude, "longitude": longitude},
    }


@app.get("/history/weather")
async def weather_history(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    days: int = Query(default=30, ge=1, le=365),
) -> dict[str, Any]:
    from app.services.history_service import (
        HistoryProviderError,
        get_weather_history,
    )

    try:
        return await get_weather_history(latitude, longitude, days=days)
    except HistoryProviderError as error:
        raise HTTPException(
            status_code=error.status_code or 503,
            detail=str(error),
        ) from error


@app.get("/analytics/model-status")
def model_status() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "model": None,
        "reason": "No verified, labeled local crop-risk dataset is configured for training or validation.",
    }


@app.get("/satellite/status")
def satellite_status() -> dict[str, Any]:
    from importlib.util import find_spec

    if find_spec("rasterio") is None or find_spec("numpy") is None:
        return {
            "status": "unavailable",
            "provider": "Sentinel-2 L2A via Earth Search STAC",
            "ndvi": "unavailable",
            "reason": "Install the satellite dependencies: pip install rasterio numpy.",
        }
    return {
        "status": "available",
        "provider": "Sentinel-2 L2A via Earth Search STAC",
        "ndvi": "computed on request at GET /satellite/ndvi (cloud-masked, 1 km window around the point)",
        "reason": "NDVI is an area average, not a per-field crop-health measurement; cloudy scenes are skipped.",
    }


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "ClimateGuard AI is running."}
