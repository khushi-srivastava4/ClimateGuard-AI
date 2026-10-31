"""Emergency-response and supply-chain logistics agent ("swarm" of cooperating steps).

OBSERVE  live weather + river-discharge hazard for every registered zone (Open-Meteo, GloFAS)
PLAN     match zone needs to supplier stock (live inventory APIs or manually kept stock), nearest first
ROUTE    OSRM driving routes with alternatives; sample each route and check forecast hazard along it
ACT      pick the safest route, assign the nearest fleet vehicle, create the order and call the supplier's webhook
RECOVER  unsafe route / empty stock / failed webhook -> try the next route, then the next supplier

Everything is recorded step by step so a human can audit what the agent did. Nothing is simulated: with no suppliers,
zones or fleet registered, the agent reports exactly that.
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.config import settings
from app.security import (
    SupplierURLValidationError,
    fetch_supplier_response,
    parse_supplier_json,
)
from app.services import ops_store as S
from app.services import live_data as L

OSRM_URL = settings.OSRM_URL
LEVELS = {"none": 0, "watch": 1, "high": 2, "severe": 3}


def haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


# ---------------------------------------------------------------- hazard model (IMD rainfall classes)
def rain_level(mm_24h: float) -> str:
    return "severe" if mm_24h >= 115.6 else "high" if mm_24h >= 64.5 else "watch" if mm_24h >= 35 else "none"


def zone_level(rain_24h: Optional[float], tmax: Optional[float], river_ratio: Optional[float]) -> Tuple[str, List[str]]:
    lvl, why = "none", []

    def bump(l: str, msg: str):
        nonlocal lvl
        why.append(msg)
        if LEVELS[l] > LEVELS[lvl]:
            lvl = l

    if rain_24h is not None and rain_level(rain_24h) != "none":
        bump(rain_level(rain_24h), f"{rain_24h:.0f} mm rain forecast in 24 h")
    if tmax is not None and tmax >= 40:
        bump("severe" if tmax >= 47 else "high" if tmax >= 45 else "watch", f"maximum temperature {tmax:.0f} C forecast")
    if river_ratio is not None and river_ratio >= 2:
        bump("severe" if river_ratio >= 5 else "high" if river_ratio >= 3 else "watch", f"river discharge forecast at {river_ratio:.1f}x its 60-day median")
    return lvl, why


async def zone_hazard(zone: Dict[str, Any]) -> Dict[str, Any]:
    lat, lon = zone["lat"], zone["lon"]
    fc, fl = await asyncio.gather(
        L.fetch("open-meteo/forecast", "https://api.open-meteo.com/v1/forecast", {
            "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 3,
            "daily": "precipitation_sum,temperature_2m_max"}, ttl=900),
        L.flood(lat, lon), return_exceptions=True)
    if isinstance(fc, Exception):
        return {"zone": zone["id"], "level": "unknown", "reasons": [f"forecast unavailable: {fc}"]}
    d = fc["daily"]
    rain24 = max([x for x in d["precipitation_sum"][:2] if x is not None] or [0.0])
    tmax = max([x for x in d["temperature_2m_max"][:2] if x is not None] or [0.0])
    ratio = None
    if not isinstance(fl, Exception) and fl.get("daily"):
        vals = fl["daily"].get("river_discharge") or []
        past = [v for v in vals[:60] if v is not None]
        fut = [v for v in vals[60:] if v is not None]
        if len(past) >= 10 and fut:
            ordered = sorted(past)
            med = ordered[len(ordered) // 2]
            ratio = max(fut) / med if med > 0.01 else None
    lvl, why = zone_level(rain24, tmax, ratio)
    return {"zone": zone["id"], "name": zone.get("name"), "level": lvl, "reasons": why, "rain_24h_mm": rain24,
            "tmax_c": tmax, "river_ratio": round(ratio, 2) if ratio else None}


# ---------------------------------------------------------------- routing
def sample_path(coords: List[List[float]], every_km: float = 10.0, cap: int = 30) -> List[Tuple[float, float]]:
    """coords are GeoJSON [lon, lat]. Returns (lat, lon) samples roughly every `every_km`, always incl. both ends."""
    if not coords:
        return []
    pts = [(coords[0][1], coords[0][0])]
    acc = 0.0
    for a, b in zip(coords, coords[1:]):
        acc += haversine_km((a[1], a[0]), (b[1], b[0]))
        if acc >= every_km:
            pts.append((b[1], b[0])); acc = 0.0
    pts.append((coords[-1][1], coords[-1][0]))
    if len(pts) > cap:
        step = len(pts) / cap
        pts = [pts[int(i * step)] for i in range(cap)] + [pts[-1]]
    return pts


def score_route(route: Dict[str, Any], point_rain: List[float]) -> Dict[str, Any]:
    levels = [rain_level(x) for x in point_rain]
    sev, high = levels.count("severe"), levels.count("high")
    hours = route["duration_s"] / 3600.0
    return {"distance_km": round(route["distance_m"] / 1000, 1), "duration_h": round(hours, 2), "severe_points": sev, "high_points": high,
            "max_rain_mm": round(max(point_rain), 1) if point_rain else None, "points_checked": len(point_rain),
            "safe": sev == 0, "cost": hours + 6 * high + 24 * sev}


async def osrm_routes(a: Tuple[float, float], b: Tuple[float, float]) -> List[Dict[str, Any]]:
    url = f"{OSRM_URL}/route/v1/driving/{a[1]},{a[0]};{b[1]},{b[0]}"
    j = await L.fetch("osrm", url, {"alternatives": "true", "overview": "simplified", "geometries": "geojson", "steps": "false"}, ttl=600, retries=1)
    if j.get("code") != "Ok" or not j.get("routes"):
        raise L.SourceError("osrm", f"no drivable route ({j.get('code')})")
    return j["routes"]


async def safest_route(a: Tuple[float, float], b: Tuple[float, float], eta_days: int = 0) -> Dict[str, Any]:
    routes = await osrm_routes(a, b)
    scored = []
    for r in routes[:3]:
        pts = sample_path(r["geometry"]["coordinates"])
        grid = await L.grid_forecast(pts)
        day = min(eta_days + int(r["duration_s"] // 86400), 6)
        rain = [(g["daily"]["precipitation_sum"][day] or 0.0) if g.get("daily") else 0.0 for g in grid]
        sc = score_route(r, rain)
        sc["path"] = [[round(c[1], 4), round(c[0], 4)] for c in r["geometry"]["coordinates"][:: max(1, len(r["geometry"]["coordinates"]) // 150)]]
        scored.append(sc)
    scored.sort(key=lambda x: x["cost"])
    best = scored[0]
    best["alternatives_considered"] = len(scored)
    return best


# ---------------------------------------------------------------- inventory + dispatch
def _norm_stock(payload: Any) -> Dict[str, float]:
    items = payload.get("items", payload) if isinstance(payload, dict) else payload
    out: Dict[str, float] = {}
    if isinstance(items, dict):
        for k, v in items.items():
            if isinstance(v, (int, float)):
                out[str(k).lower()] = float(v)
    elif isinstance(items, list):
        for it in items:
            if isinstance(it, dict) and "item" in it and isinstance(it.get("qty"), (int, float)):
                out[str(it["item"]).lower()] = out.get(str(it["item"]).lower(), 0.0) + float(it["qty"])
    return out


async def supplier_stock(sup: Dict[str, Any]) -> Tuple[Dict[str, float], str]:
    if sup.get("inventory_url"):
        try:
            _, body = await fetch_supplier_response(
                "GET",
                sup["inventory_url"],
                headers=sup.get("inventory_headers") or {},
            )
            return _norm_stock(parse_supplier_json(body)), "live inventory API"
        except SupplierURLValidationError:
            raise
        except Exception as e:
            return {}, f"inventory API failed ({type(e).__name__})"
    return _norm_stock(sup.get("stock") or []), "manually maintained stock"


async def send_webhook(sup: Dict[str, Any], order: Dict[str, Any]) -> str:
    if not sup.get("webhook_url"):
        return "ready_to_dispatch (no webhook configured for this supplier)"
    for attempt in range(2):
        try:
            status, _ = await fetch_supplier_response(
                "POST",
                sup["webhook_url"],
                json_body=order,
                headers=sup.get("webhook_headers") or {},
            )
            if status < 300:
                return "dispatched"
            if status < 500:
                return f"dispatch_rejected (HTTP {status})"
        except SupplierURLValidationError:
            raise
        except Exception:
            pass
        await asyncio.sleep(1 + attempt)
    return "dispatch_failed (supplier webhook unreachable)"


def nearest_vehicle(fleet: List[Dict[str, Any]], origin: Tuple[float, float]) -> Optional[Dict[str, Any]]:
    free = [v for v in fleet if v.get("status", "available") == "available" and v.get("lat") is not None]
    return min(free, key=lambda v: haversine_km((v["lat"], v["lon"]), origin)) if free else None


# ---------------------------------------------------------------- the agent loop
async def run_cycle(min_level: str = "high", dry_run: bool = False) -> Dict[str, Any]:
    log: List[Dict[str, Any]] = []

    def step(stage: str, msg: str, ok: bool = True, **extra):
        log.append({"ts": time.time(), "stage": stage, "ok": ok, "msg": msg, **extra})

    zones, suppliers, fleet = S.list_docs("zone"), S.list_docs("supplier"), S.list_docs("fleet")
    orders_made: List[Dict[str, Any]] = []
    if not zones:
        step("observe", "No zones registered: add the communities or sites this agent should protect.", ok=False)
    haz = await asyncio.gather(*[zone_hazard(z) for z in zones])
    for h in haz:
        step("observe", f"{h.get('name') or h['zone']}: hazard {h['level']}" + (f" ({'; '.join(h['reasons'])})" if h.get("reasons") else ""))
    active_orders = [o for o in S.list_docs("order") if o["status"] not in ("delivered", "cancelled") and time.time() - o["created"] < 86400]

    for z, h in zip(zones, haz):
        if LEVELS.get(h["level"], -1) < LEVELS[min_level]:
            continue
        if not suppliers:
            step("plan", f"{z['name']}: hazard {h['level']} but no suppliers are registered.", ok=False); continue
        covered = {(o["zone"], it["item"]) for o in active_orders for it in o["items"]}
        for need in z.get("needs", []):
            item, qty = need["item"].lower(), float(need["qty"])
            if (z["id"], item) in covered:
                step("plan", f"{z['name']}: {item} already covered by an open order, skipping."); continue
            remaining = qty
            ranked = sorted(suppliers, key=lambda s: haversine_km((s["lat"], s["lon"]), (z["lat"], z["lon"])))
            for sup in ranked:
                if remaining <= 0:
                    break
                stock, how = await supplier_stock(sup)
                have = stock.get(item, 0.0)
                if have <= 0:
                    step("plan", f"{sup['name']}: no {item} in stock ({how}).", ok=False); continue
                take = min(have, remaining)
                try:
                    route = await safest_route((sup["lat"], sup["lon"]), (z["lat"], z["lon"]))
                except Exception as e:
                    step("route", f"{sup['name']} -> {z['name']}: routing failed ({e}); trying next supplier.", ok=False); continue
                if not route["safe"]:
                    step("route", f"{sup['name']} -> {z['name']}: every route crosses a severe-rain area; trying next supplier.", ok=False, route=route); continue
                veh = nearest_vehicle(fleet, (sup["lat"], sup["lon"]))
                order = {"id": uuid.uuid4().hex[:10], "created": time.time(), "zone": z["id"], "zone_name": z["name"],
                         "supplier": sup["id"], "supplier_name": sup["name"], "items": [{"item": item, "qty": take}],
                         "vehicle": veh["id"] if veh else None, "route": route, "hazard": h["level"],
                         "stock_source": how, "status": "planned"}
                if dry_run:
                    order["status"] = "dry_run (nothing sent)"
                else:
                    order["status"] = await send_webhook(sup, order)
                    if not sup.get("inventory_url"):       # reserve manually-kept stock so it is not promised twice
                        for row in sup.get("stock", []):
                            if str(row["item"]).lower() == item:
                                row["qty"] = max(0.0, float(row["qty"]) - take)
                        S.put("supplier", sup["id"], sup)
                    if veh:
                        veh["status"] = "assigned"; S.put("fleet", veh["id"], veh)
                    S.put("order", order["id"], order)
                orders_made.append(order)
                step("act", f"{item} x{take:g}: {sup['name']} -> {z['name']} {route['distance_km']} km, {route['duration_h']} h, "
                            f"vehicle {order['vehicle'] or 'none registered'}, status: {order['status']}", order=order["id"])
                remaining -= take
            if remaining > 0:
                step("plan", f"{z['name']}: {remaining:g} of {qty:g} {item} could not be sourced.", ok=False)
    run = {"started": log[0]["ts"] if log else time.time(), "min_level": min_level, "dry_run": dry_run, "hazards": haz,
           "orders": [o["id"] for o in orders_made], "steps": log}
    if not dry_run:
        S.add_event("run", None, run)
    return {**run, "order_details": orders_made}
