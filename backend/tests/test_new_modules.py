"""Unit tests. Synthetic payloads live ONLY here (to exercise the logic); the app itself never uses fixtures."""
import asyncio
from datetime import date, timedelta
import pytest
from app.services import climate_risk as R, action_planner as AP, alert_engine as AE, grounding as G, llm_router as LR, soil_live as SS
from app.services.crop_profiles import CROPS


def make_fc(tmax=30.0, rain=0.0, et0=4.0, sm=0.25, soil_t=20.0, future_rain=None, future_tmax=None):
    start = date(2026, 10, 1)
    t = [(start + timedelta(d)).isoformat() for d in range(46)]
    pr = [rain] * 30 + (future_rain or [rain] * 16)
    tx = [tmax] * 30 + (future_tmax or [tmax] * 16)
    hours = [f"{d}T{h:02d}:00" for d in t for h in range(24)]
    return {"daily": {"time": t, "temperature_2m_max": tx, "temperature_2m_min": [15] * 46, "precipitation_sum": pr,
                      "et0_fao_evapotranspiration": [et0] * 46, "precipitation_probability_max": [10] * 46},
            "hourly": {"time": hours, "soil_moisture_0_to_7cm": [sm] * len(hours), "soil_moisture_7_to_28cm": [sm] * len(hours),
                       "soil_temperature_6cm": [soil_t] * len(hours)}}


CLIM = {"PRECTOTCORR": {m: 1.0 for m in R.MONTHS}}
SOIL = {"clay_pct": 25}


def test_heat_hot_forecast_is_severe():
    a = R.assess(make_fc(future_tmax=[41] * 16), None, CLIM, SOIL, CROPS["wheat"])
    assert a["risks"]["heat"]["score"] >= 75


def test_stage_lowers_heat_threshold():
    fc = make_fc(future_tmax=[31] * 16)
    base = R.assess(fc, None, CLIM, SOIL, CROPS["wheat"])["risks"]["heat"]["score"]
    sensitive = R.assess(fc, None, CLIM, SOIL, CROPS["wheat"], stage="grain filling")["risks"]["heat"]["score"]
    assert base < 25 <= sensitive          # 31°C is a small early warning normally, a real hazard at grain filling


def test_heavy_rain_flags_waterlogging():
    a = R.assess(make_fc(future_rain=[0, 0, 0, 80, 90, 70] + [0] * 10), None, CLIM, SOIL, CROPS["wheat"])
    assert a["risks"]["flood"]["score"] >= 75 and a["peak_rain"]["mm"] >= 200


def test_dry_soil_flags_drought():
    a = R.assess(make_fc(sm=0.08, et0=7), None, CLIM, SOIL, CROPS["maize"])
    assert a["risks"]["drought"]["score"] >= 50 and a["water"]["weekly_irrigation_mm"][0] > 30


def test_calm_conditions_all_low_and_missing_data_ok():
    a = R.assess(make_fc(tmax=24, rain=2.0, et0=2.0, sm=0.3), None, None, None, CROPS["wheat"])
    assert all(r["score"] < 40 for r in a["risks"].values())


def test_planner_is_conditional_and_deduplicated():
    dry = R.assess(make_fc(sm=0.08, et0=7), None, CLIM, SOIL, CROPS["maize"], "vegetative")
    acts = AP.plan_actions(dry, "maize", "vegetative")
    assert any(x["category"] == "irrigation" for x in acts)
    assert len({x["key"] for x in acts}) == len(acts) <= 10
    calm = R.assess(make_fc(tmax=24, rain=2.0, et0=2.0, sm=0.3), None, CLIM, SOIL, CROPS["wheat"], "tillering")
    assert not any(x["category"] == "irrigation" for x in AP.plan_actions(calm, "wheat", "tillering"))


def test_alerts_threshold_and_dedupe():
    a = R.assess(make_fc(future_tmax=[41] * 16), None, CLIM, SOIL, CROPS["wheat"])
    al = AE.build_alerts(1, a, True, 60, today=date(2026, 10, 31))
    assert al and al[0]["hazard"] == "heat"
    assert AE.only_new(al, [x["dedupe_key"] for x in al]) == []
    assert AE.build_alerts(1, a, False) == []


def test_grounding_flags_invented_numbers():
    data = {"rain": "forecast rain 42 mm", "price": 2300.0}
    assert G.check("Expect 42 mm of rain; price ₹2,300", data)["unverified"] == []
    assert G.check("Expect 90 mm of rain", data)["unverified"] == [90.0]


def test_soil_type_fallback_mapping():
    assert SS.clay_from_soil_type("Sandy loam") == 14 and SS.clay_from_soil_type("Black cotton") == 52 and SS.clay_from_soil_type("xyz") is None


def test_llm_router_fails_over_and_cools_down(monkeypatch):
    calls = []
    monkeypatch.setattr(LR, "providers", lambda: [{"name": "gemini", "kind": "GEMINI", "key": "k", "model": "m"},
                                                  {"name": "anthropic", "kind": "ANTHROPIC", "key": "k", "model": "m"}])

    async def fake_call(p, prompt, system):
        calls.append(p["name"])
        if p["name"] == "gemini":
            raise LR.ProviderError("HTTP 429 (quota or rate limit)", 429, 60)
        return "ok text"

    monkeypatch.setattr(LR, "_call", fake_call)
    LR.COOLDOWN.clear(); LR.CACHE.clear()
    r = asyncio.run(LR.generate("p1", "s"))
    assert r["provider"] == "anthropic" and r["attempts"][0]["ok"] is False
    asyncio.run(LR.generate("p2", "s"))
    assert calls == ["gemini", "anthropic", "anthropic"]      # gemini is not called again while cooling down


def test_llm_router_skip_and_all_fail(monkeypatch):
    monkeypatch.setattr(LR, "providers", lambda: [{"name": "gemini", "kind": "GEMINI", "key": "k", "model": "m"}])
    LR.COOLDOWN.clear(); LR.CACHE.clear()
    with pytest.raises(LR.AllProvidersFailed):
        asyncio.run(LR.generate("p", "s", skip=["gemini"]))      # primary skipped, nothing else configured


def test_insights_endpoint_end_to_end_with_partial_failures(monkeypatch):
    """Router wiring: forecast works, soil/market/river fail -> still a valid assessment with warnings (no 500)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import insights as I
    from app.services import live_data as L, soil_live, mandi_live

    async def fc(lat, lon): return make_fc(future_tmax=[39] * 16)
    async def clim(lat, lon): return CLIM
    async def enso(): return {"phase": "Neutral", "oni": 0.1, "season": "ASO 2026"}
    async def boom(*a, **k): raise L.SourceError("x", "down")
    monkeypatch.setattr(L, "forecast", fc); monkeypatch.setattr(L, "climatology", clim); monkeypatch.setattr(L, "enso", enso)
    monkeypatch.setattr(L, "flood", boom); monkeypatch.setattr(soil_live, "get_soil", boom); monkeypatch.setattr(mandi_live, "get_mandi", boom)
    app = FastAPI(); app.include_router(I.router); c = TestClient(app)
    r = c.get("/insights/risk", params={"lat": 27.1, "lon": 78.0, "crop": "wheat", "state": "Uttar Pradesh"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["risks"]["heat"]["score"] >= 75 and j["actions_v2"]
    assert any("flood unavailable" in w or "soil unavailable" in w for w in j["warnings"]) and j["market"] is None


def test_insights_assessment_stops_when_forecast_is_unavailable(monkeypatch):
    from fastapi import HTTPException
    from app.routers import insights as I
    from app.services import live_data as L, soil_live

    async def unavailable(*args, **kwargs):
        raise L.SourceError("open-meteo/forecast", "HTTP 429: rate limited")

    monkeypatch.setattr(L, "forecast", unavailable)
    monkeypatch.setattr(L, "flood", unavailable)
    monkeypatch.setattr(L, "climatology", unavailable)
    monkeypatch.setattr(L, "enso", unavailable)
    monkeypatch.setattr(soil_live, "get_soil", unavailable)

    with pytest.raises(HTTPException) as error:
        asyncio.run(I.build(27.1, 78.0, "wheat"))
    assert error.value.status_code == 503
    assert "no assessment can be made" in error.value.detail.lower()


def test_climate_assessment_rejects_missing_required_forecast_values():
    from app.services import climate_risk

    forecast = make_fc()
    forecast["daily"]["temperature_2m_max"][30] = None
    with pytest.raises(ValueError, match="temperature_2m_max"):
        climate_risk.assess(forecast, None, CLIM, SOIL, CROPS["wheat"])

    short_forecast = make_fc()
    for series in short_forecast["daily"].values():
        del series[43:]
    with pytest.raises(ValueError, match="too short"):
        climate_risk.assess(short_forecast, None, CLIM, SOIL, CROPS["wheat"])
