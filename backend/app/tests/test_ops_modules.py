"""Tests for grid controller, relief agent, validation and ops endpoints. Synthetic inputs exist ONLY here."""
import asyncio, time
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routers import ops
from app.services import gridctl, swarm, validation, ops_store as S, live_data as L


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("OPS_DB", str(tmp_path / "ops.sqlite3"))


def day_hourly(temp=30.0, peak=900.0):
    times = [f"2026-10-31T{h:02d}:00" for h in range(24)]
    ghi = [max(0.0, peak * (1 - ((h - 12) / 6) ** 2)) if 6 <= h <= 18 else 0.0 for h in range(24)]
    return {"time": times, "ghi": ghi, "temp": [temp] * 24, "source": "test"}


SITE = {"id": "clinic", "name": "Clinic", "lat": 27, "lon": 78, "pv_kwp": 10, "inverter_kw": 8, "battery_kwh": 20,
        "battery_min_soc_pct": 20, "grid_import_limit_kw": 0,
        "loads": [{"name": "vaccine fridge", "kw": 0.5, "priority": 1},
                  {"name": "ac", "kw": 3, "priority": 3, "cooling": True},
                  {"name": "laundry", "kw": 2, "priority": 5, "deferrable": True, "run_hours": 2}]}


def test_pv_model_zero_at_night_and_capped_by_inverter():
    assert gridctl.pv_kw(0, 20, SITE) == 0
    assert gridctl.pv_kw(1000, 25, {**SITE, "inverter_kw": 3}) == 3


def test_deferrable_load_runs_in_solar_hours_and_critical_is_served():
    p = gridctl.plan(SITE, day_hourly(35), {"soc_pct": 60, "grid_available": False}, 24)
    laundry = next(d for d in p["deferred_loads"] if d["load"] == "laundry")
    assert all(10 <= int(t[11:13]) <= 14 for t in laundry["run_at"])
    assert p["summary"]["critical_shortfall_hours"] == []


def test_battery_empty_and_no_pv_sheds_noncritical_first_then_flags_critical():
    site = {**SITE, "pv_kwp": 0}
    p = gridctl.plan(site, day_hourly(), {"soc_pct": 21, "grid_available": False}, 24)
    night = p["rows"][2]
    assert "ac" in night["shed"] or night["served_kw"] <= 0.5 + 1e-9
    assert p["summary"]["unserved_kwh"] > 0 and p["recommendations"]


def test_unknown_battery_is_reported_not_invented():
    p = gridctl.plan(SITE, day_hourly(), {"soc_pct": None, "grid_available": True}, 24)
    assert any("unknown" in w for w in p["warnings"]) and all(r["soc_pct"] is None for r in p["rows"])


def test_heatwave_raises_cooling_demand_and_flags():
    cool = gridctl.plan(SITE, day_hourly(28), {"soc_pct": 80}, 24)["summary"]["demand_kwh"]
    hot = gridctl.plan(SITE, day_hourly(46), {"soc_pct": 80}, 24)
    assert hot["summary"]["demand_kwh"] > cool and hot["summary"]["heatwave"] == "severe"


def test_water_pump_scheduled_when_tank_low():
    site = {**SITE, "tank_l": 10000, "water_demand_lph": 400, "pump_kw": 1.5, "pump_lph": 2000}
    p = gridctl.plan(site, day_hourly(38), {"soc_pct": 70, "tank_pct": 30}, 24)
    assert p["water"]["pump_hours_needed"] >= 1 and any(d["load"] == "water pump" for d in p["deferred_loads"])


def test_zone_levels_follow_imd_classes():
    assert swarm.zone_level(120, None, None)[0] == "severe"
    assert swarm.zone_level(70, None, None)[0] == "high"
    assert swarm.zone_level(10, 30, 1.0)[0] == "none"
    assert swarm.zone_level(None, 46, None)[0] == "high"


def test_route_scoring_prefers_dry_route_even_if_longer():
    short = {"distance_m": 50000, "duration_s": 3600}
    long_ = {"distance_m": 80000, "duration_s": 6000}
    assert swarm.score_route(short, [130, 20])["safe"] is False
    assert swarm.score_route(long_, [10, 20])["cost"] < swarm.score_route(short, [130, 20])["cost"]


def test_agent_recovers_from_unsafe_route_by_switching_supplier(monkeypatch):
    S.put("zone", "village", {"id": "village", "name": "Village", "lat": 26.0, "lon": 78.0, "needs": [{"item": "water", "qty": 100}]})
    S.put("supplier", "near", {"id": "near", "name": "Near depot", "lat": 26.1, "lon": 78.0, "stock": [{"item": "water", "qty": 500}]})
    S.put("supplier", "far", {"id": "far", "name": "Far depot", "lat": 27.0, "lon": 78.0, "stock": [{"item": "water", "qty": 500}]})
    S.put("fleet", "truck1", {"id": "truck1", "lat": 27.0, "lon": 78.0, "status": "available"})

    async def haz(z): return {"zone": z["id"], "name": z["name"], "level": "severe", "reasons": ["130 mm rain forecast in 24 h"]}
    async def route(a, b, eta_days=0):
        if abs(a[0] - 26.1) < 0.01:      # the nearest depot's road is flooded
            return {"safe": False, "distance_km": 10, "duration_h": 0.3, "severe_points": 2, "high_points": 0, "path": []}
        return {"safe": True, "distance_km": 110, "duration_h": 2.2, "severe_points": 0, "high_points": 0, "path": [[27, 78], [26, 78]], "max_rain_mm": 20}
    monkeypatch.setattr(swarm, "zone_hazard", haz); monkeypatch.setattr(swarm, "safest_route", route)
    res = asyncio.run(swarm.run_cycle("high"))
    assert len(res["order_details"]) == 1 and res["order_details"][0]["supplier"] == "far"
    assert res["order_details"][0]["vehicle"] == "truck1" and "ready_to_dispatch" in res["order_details"][0]["status"]
    assert any(s["stage"] == "route" and not s["ok"] for s in res["steps"])          # the failure was logged
    assert S.get("supplier", "far")["stock"][0]["qty"] == 400                         # stock reserved
    again = asyncio.run(swarm.run_cycle("high"))                                      # no duplicate order
    assert again["order_details"] == []


def test_agent_reports_missing_setup_instead_of_inventing():
    res = asyncio.run(swarm.run_cycle())
    assert res["order_details"] == [] and any("No zones registered" in s["msg"] for s in res["steps"])


def test_validation_needs_labels_then_computes_metrics():
    assert validation.status()["status"] == "unvalidated"
    base = time.time() - 5 * 86400
    for i in range(40):
        score = 80 if i % 2 == 0 else 10
        S.add_event("prediction", "x", {"lat": 10 + i * 0.5, "lon": 78, "crop": "wheat", "scores": {"heat": score, "drought": 0, "flood": 0, "unseasonal_rain": 0}}, ts=base - i)
        S.add_event("outcome", None, {"lat": 10.01 + i * 0.5, "lon": 78, "crop": "wheat", "event": "heat" if score == 80 else "none",
                                      "observed_date": "x", "observed_ts": base + 3 * 86400 - i})
    s = validation.status()
    assert s["hazards"]["heat"]["status"] == "evaluated" and s["hazards"]["heat"]["auc"] == 1.0
    assert s["hazards"]["drought"]["status"] == "insufficient labels"


def test_api_endpoints(monkeypatch):
    app = FastAPI(); app.include_router(ops.router); c = TestClient(app)
    assert c.post("/grid/sites", json={"name": "Clinic", "lat": 27, "lon": 78, "pv_kwp": 5, "battery_kwh": 10,
                                       "loads": [{"name": "fridge", "kw": 0.4, "priority": 1}]}).status_code == 201
    assert c.post("/grid/telemetry", json={"site_id": "clinic", "soc_pct": 55, "grid_available": True}).status_code == 201
    assert c.post("/grid/telemetry", json={"site_id": "nope"}).status_code == 404

    async def fake_hourly(lat, lon, hours): return day_hourly()
    monkeypatch.setattr(gridctl, "hourly_forecast", fake_hourly)
    j = c.get("/grid/plan/clinic").json()
    assert j["telemetry"]["used"] and j["telemetry"]["soc_pct"] == 55 and len(j["rows"]) == 24

    async def boom(*a, **k): raise L.SourceError("open-meteo", "down")
    monkeypatch.setattr(gridctl, "hourly_forecast", boom)
    assert c.get("/grid/plan/clinic").status_code == 503
    assert c.post("/analytics/outcomes", json={"lat": 27, "lon": 78, "event": "heat", "observed_date": "2999-01-01"}).status_code == 422
    assert c.post("/analytics/outcomes", json={"lat": 27, "lon": 78, "event": "heat", "observed_date": "2026-10-01"}).status_code == 201
    assert c.post("/relief/zones", json={"name": "Village A", "lat": 26, "lon": 78, "needs": [{"item": "water", "qty": 50}]}).status_code == 201
    assert c.delete("/relief/zones/village-a").status_code == 204


def _fc_dry():
    from datetime import date, timedelta
    start = date(2026, 10, 1)
    t = [(start + timedelta(d)).isoformat() for d in range(46)]
    hours = [f"{d}T{h:02d}:00" for d in t for h in range(24)]
    return {"daily": {"time": t, "temperature_2m_max": [32] * 46, "temperature_2m_min": [16] * 46, "precipitation_sum": [0.0] * 46,
                      "et0_fao_evapotranspiration": [6.0] * 46, "precipitation_probability_max": [5] * 46},
            "hourly": {"time": hours, "soil_moisture_0_to_7cm": [0.08] * len(hours), "soil_moisture_7_to_28cm": [0.09] * len(hours),
                       "soil_temperature_6cm": [22] * len(hours)}}


def test_advise_graph_gets_real_drought_score(monkeypatch):
    from app.agent import graph
    from app.services import drought

    async def fc(lat, lon): return _fc_dry()
    async def clim(lat, lon): return {"PRECTOTCORR": {m: 2.0 for m in ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]}}
    monkeypatch.setattr(L, "forecast", fc); monkeypatch.setattr(L, "climatology", clim)
    state = {"latitude": 27.0, "longitude": 78.0, "crop": "maize", "growth_stage": "vegetative",
             "weather": {"max_temp": 32, "precipitation_total": 0, "daily": [], "retrieved_at": "2026-10-31T00:00:00+00:00"},
             "soil": {"properties": {"clay": 25}}, "mandi": {}}
    out = asyncio.run(graph.compute_risk_node(state))["risk"]
    assert out["drought"] is not None and out["drought"] >= 50
    assert out["overall"] >= out["drought"]
    assert not any(q.startswith("Drought indicator unavailable") for q in out["data_quality"])

    async def boom(*a, **k): raise L.SourceError("open-meteo", "down")
    monkeypatch.setattr(drought.L, "forecast", boom)
    out2 = asyncio.run(graph.compute_risk_node(dict(state)))["risk"]
    assert out2["drought"] is None           # unavailable, never silently zero
