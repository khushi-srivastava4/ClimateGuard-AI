"""Operational endpoints: smart-grid controller, relief logistics agent, voice/chat assistant, outcome validation."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.routers.insights import build
from app.services import advisory_service, gridctl, ops_store as S, swarm, translation_service, validation
from app.services.live_data import SourceError

router = APIRouter(tags=["operations"])
logger = logging.getLogger(__name__)
slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "item"


# ------------------------------------------------------------------ smart grid controller
class Load(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kw: float = Field(gt=0, le=10000)
    priority: int = Field(default=3, ge=1, le=5, description="1 = life-critical ... 5 = fully deferrable")
    cooling: bool = False
    deferrable: bool = False
    run_hours: float | None = Field(default=None, gt=0, le=24)
    window: list[int] | None = None


class Site(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    pv_kwp: float = Field(default=0, ge=0)
    inverter_kw: float | None = Field(default=None, gt=0)
    battery_kwh: float = Field(default=0, ge=0)
    battery_min_soc_pct: float = Field(default=20, ge=0, le=90)
    grid_import_limit_kw: float = Field(default=0, ge=0)
    tank_l: float | None = Field(default=None, gt=0)
    water_demand_lph: float | None = Field(default=None, gt=0)
    pump_kw: float | None = Field(default=None, gt=0)
    pump_lph: float | None = Field(default=None, gt=0)
    loads: list[Load] = Field(default_factory=list)


class Telemetry(BaseModel):
    site_id: str
    soc_pct: float | None = Field(default=None, ge=0, le=100)
    tank_pct: float | None = Field(default=None, ge=0, le=100)
    load_kw: float | None = Field(default=None, ge=0)
    pv_kw: float | None = Field(default=None, ge=0)
    grid_available: bool = True


def _site(site_id: str) -> Dict[str, Any]:
    s = S.get("site", site_id)
    if not s:
        raise HTTPException(404, f"unknown site '{site_id}'")
    return s


@router.post("/grid/sites", status_code=201)
def save_site(site: Site) -> Dict[str, Any]:
    doc = {**site.model_dump(), "id": slug(site.name)}
    return S.put("site", doc["id"], doc)


@router.get("/grid/sites")
def list_sites() -> List[Dict[str, Any]]:
    return S.list_docs("site")


@router.delete("/grid/sites/{site_id}", status_code=204)
def delete_site(site_id: str) -> Response:
    if not S.delete("site", site_id):
        raise HTTPException(404, "unknown site")
    return Response(status_code=204)


@router.post("/grid/telemetry", status_code=201)
def post_telemetry(t: Telemetry) -> Dict[str, Any]:
    _site(t.site_id)
    S.add_event("telemetry", t.site_id, t.model_dump())
    return {"stored": True}


@router.get("/grid/telemetry/{site_id}")
def get_telemetry(site_id: str, limit: int = Query(48, ge=1, le=500)) -> List[Dict[str, Any]]:
    return S.events("telemetry", site_id, limit=limit)


@router.get("/grid/plan/{site_id}")
async def grid_plan(site_id: str, hours: int = Query(24, ge=6, le=48), outage_hours: Optional[str] = None,
                    stale_after_min: int = Query(180, ge=5, le=1440)) -> Dict[str, Any]:
    site = _site(site_id)
    last = S.events("telemetry", site_id, limit=1)
    state: Dict[str, Any] = {"soc_pct": None, "tank_pct": None, "grid_available": True}
    age = None
    if last:
        age = (time.time() - last[0]["ts"]) / 60
        if age <= stale_after_min:
            state = {k: last[0].get(k) for k in state}
    try:
        hourly = await gridctl.hourly_forecast(site["lat"], site["lon"], hours)
    except SourceError as e:
        raise HTTPException(503, f"Weather forecast unavailable, cannot plan: {e.msg}")
    outage = [int(x) for x in outage_hours.split(",") if x.strip().isdigit()] if outage_hours else None
    result = gridctl.plan(site, hourly, state, hours, outage)
    result["telemetry"] = {"used": bool(last) and age is not None and age <= stale_after_min, "age_minutes": round(age) if age is not None else None, **state}
    if last and age is not None and age > stale_after_min:
        result["warnings"].append(f"Latest telemetry is {round(age)} min old (limit {stale_after_min}); it was ignored.")
    return result


# ------------------------------------------------------------------ relief logistics agent
class Need(BaseModel):
    item: str = Field(min_length=1, max_length=40)
    qty: float = Field(gt=0)


class Zone(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    population: int | None = Field(default=None, ge=0)
    needs: list[Need] = Field(default_factory=list)


class StockRow(BaseModel):
    item: str
    qty: float = Field(ge=0)


class Supplier(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    inventory_url: str | None = Field(default=None, description="GET endpoint returning {items:[{item,qty}]} or {item: qty}")
    webhook_url: str | None = Field(default=None, description="POST endpoint that receives the dispatch order")
    stock: list[StockRow] = Field(default_factory=list, description="used only when no inventory_url is given")


class VehicleTelemetry(BaseModel):
    vehicle_id: str = Field(min_length=1, max_length=40)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    capacity_kg: float | None = Field(default=None, gt=0)
    status: Literal["available", "assigned", "offline"] = "available"


class RunRequest(BaseModel):
    min_level: Literal["watch", "high", "severe"] = "high"
    dry_run: bool = False


@router.post("/relief/zones", status_code=201)
def save_zone(z: Zone) -> Dict[str, Any]:
    doc = {**z.model_dump(), "id": slug(z.name)}
    return S.put("zone", doc["id"], doc)


@router.get("/relief/zones")
def list_zones() -> List[Dict[str, Any]]:
    return S.list_docs("zone")


@router.post("/relief/suppliers", status_code=201)
def save_supplier(s: Supplier) -> Dict[str, Any]:
    doc = {**s.model_dump(), "id": slug(s.name)}
    return S.put("supplier", doc["id"], doc)


@router.get("/relief/suppliers")
def list_suppliers() -> List[Dict[str, Any]]:
    return S.list_docs("supplier")


@router.post("/relief/fleet", status_code=201)
def fleet_telemetry(v: VehicleTelemetry) -> Dict[str, Any]:
    doc = {**v.model_dump(), "id": slug(v.vehicle_id), "updated": time.time()}
    return S.put("fleet", doc["id"], doc)


@router.get("/relief/fleet")
def list_fleet() -> List[Dict[str, Any]]:
    return S.list_docs("fleet")


@router.delete("/relief/{kind}/{doc_id}", status_code=204)
def delete_doc(kind: Literal["zones", "suppliers", "fleet"], doc_id: str) -> Response:
    if not S.delete({"zones": "zone", "suppliers": "supplier", "fleet": "fleet"}[kind], doc_id):
        raise HTTPException(404, "not found")
    return Response(status_code=204)


@router.get("/relief/hazards")
async def hazards() -> List[Dict[str, Any]]:
    return await asyncio.gather(*[swarm.zone_hazard(z) for z in S.list_docs("zone")])


@router.post("/relief/run")
async def relief_run(req: RunRequest) -> Dict[str, Any]:
    return await swarm.run_cycle(req.min_level, req.dry_run)


@router.get("/relief/runs")
def relief_runs(limit: int = Query(10, ge=1, le=50)) -> List[Dict[str, Any]]:
    return S.events("run", limit=limit)


@router.get("/relief/orders")
def relief_orders() -> List[Dict[str, Any]]:
    return sorted(S.list_docs("order"), key=lambda o: -o["created"])


class OrderPatch(BaseModel):
    status: Literal["delivered", "cancelled", "dispatched"]


@router.patch("/relief/orders/{order_id}")
def patch_order(order_id: str, p: OrderPatch) -> Dict[str, Any]:
    o = S.get("order", order_id)
    if not o:
        raise HTTPException(404, "unknown order")
    o["status"] = p.status
    if p.status in ("delivered", "cancelled") and o.get("vehicle"):
        v = S.get("fleet", o["vehicle"])
        if v:
            v["status"] = "available"; S.put("fleet", v["id"], v)
    return S.put("order", order_id, o)


_autopilot: Optional[asyncio.Task] = None


def start_autopilot() -> None:
    """Set RELIEF_AUTOPILOT_MINUTES=15 to let the agent run on its own; otherwise it only runs when asked."""
    global _autopilot
    minutes = float(os.getenv("RELIEF_AUTOPILOT_MINUTES", "0") or 0)
    if minutes <= 0 or _autopilot:
        return

    async def loop() -> None:
        while True:
            try:
                await swarm.run_cycle(os.getenv("RELIEF_MIN_LEVEL", "high"))
            except Exception:
                pass
            await asyncio.sleep(minutes * 60)

    _autopilot = asyncio.get_event_loop().create_task(loop())


# ------------------------------------------------------------------ conversational / voice assistant
class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class ChatRequest(BaseModel):
    lat: float = Field(ge=-60, le=70)
    lon: float = Field(ge=-180, le=180)
    crop: str = "wheat"
    stage: str | None = None
    soil_type: str | None = None
    state: str | None = None
    language: Literal["en", "hi", "bn", "mr", "ta", "te", "gu", "kn", "pa", "ml", "or", "as", "ur"] = "en"
    message: str = Field(min_length=1, max_length=600)
    history: list[ChatTurn] = Field(default_factory=list)


@router.post("/assistant/chat")
async def assistant_chat(req: ChatRequest) -> Dict[str, Any]:
    a = await build(req.lat, req.lon, req.crop, req.stage, req.soil_type, req.state)
    summary = advisory_service.build_summary(a, req.crop, req.stage, a["soil"], a["enso"], a["market"], {"state": req.state}, a["actions_v2"])
    out = await advisory_service.advise(summary, "en", req.message, [t.model_dump() for t in req.history])
    source_advisory = out["advisory"]
    if req.language != "en":
        try:
            out["advisory"] = await translation_service.translate_advisory(
                source_advisory, req.language
            )
        except translation_service.TranslationError as exc:
            logger.warning("Advisory translation failed (%s)", type(exc).__name__)
            raise HTTPException(
                status_code=_translation_status(exc),
                detail=_translation_detail(exc, req.language),
            ) from None
    out["source_advisory"] = source_advisory
    out["data_used"] = {"sources": a["sources"], "warnings": a["warnings"]}
    return out


class TranslationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    target_language: Literal["en", "hi", "bn", "mr", "ta", "te", "gu", "kn", "pa", "ml", "or", "as", "ur"]


@router.post("/assistant/translate")
async def translate_assistant_advisory(req: TranslationRequest) -> Dict[str, str]:
    try:
        translated_text = await translation_service.translate_advisory(
            req.text, req.target_language
        )
    except translation_service.TranslationError as exc:
        logger.warning("Advisory translation failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=_translation_status(exc),
            detail=_translation_detail(exc, req.target_language),
        ) from None
    return {"translated_text": translated_text}


def _translation_status(error: translation_service.TranslationError) -> int:
    if isinstance(
        error,
        (
            translation_service.TranslationNotConfigured,
            translation_service.TranslationCredentialsRejected,
        ),
    ):
        return 503
    if isinstance(error, translation_service.TranslationInsufficientCredits):
        return 503
    if isinstance(error, translation_service.TranslationTimeout):
        return 504
    return 502


def _translation_detail(error: translation_service.TranslationError, language: str) -> str:
    if isinstance(error, translation_service.TranslationNotConfigured):
        return "Translation is not configured. Set SARVAM_API_KEY on the backend."
    if isinstance(error, translation_service.TranslationCredentialsRejected):
        return "Translation service credentials were rejected. Check the backend configuration."
    if isinstance(error, translation_service.TranslationInsufficientCredits):
        return "Translation service quota or credits are unavailable. Please try again later."
    if isinstance(error, translation_service.TranslationTimeout):
        return "Translation timed out. Please try again."
    return (
        f"Translation to {advisory_service.LANGS[language]} is unavailable. "
        "Please try again or select English."
    )


# ------------------------------------------------------------------ outcome reporting for validation
class Outcome(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    crop: str = "wheat"
    event: Literal["drought", "heat", "flood", "unseasonal_rain", "none"]
    observed_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    severity: int | None = Field(default=None, ge=1, le=5)


@router.post("/analytics/outcomes", status_code=201)
def report_outcome(o: Outcome) -> Dict[str, Any]:
    try:
        return validation.add_outcome(o.lat, o.lon, o.crop, o.event, o.observed_date, o.severity)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/analytics/validation")
def validation_status() -> Dict[str, Any]:
    return validation.status()
