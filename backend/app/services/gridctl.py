"""Smart-grid and urban-resource controller.

A deliberately small, dependency-free planner that runs on edge hardware (pure Python, ~O(hours x loads)).
Inputs that are real:  Open-Meteo hourly irradiance and temperature, plus telemetry that YOUR devices post.
Nothing is simulated: when battery or tank state is unknown the plan says so and leaves that part out.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.services.live_data import fetch

PR = 0.80             # PV performance ratio (wiring, soiling, inverter); override with site["pv_pr"]
EFF = 0.92            # one-way battery efficiency
HARD_FLOOR = 0.05     # critical loads may dip to 5 % state of charge, others stop at the configured reserve
HEAT_WATCH_C, HEAT_SEVERE_C = 40.0, 45.0


async def hourly_forecast(lat: float, lon: float, hours: int = 48) -> Dict[str, Any]:
    j = await fetch("open-meteo/forecast", "https://api.open-meteo.com/v1/forecast", {
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 3,
        "hourly": "shortwave_radiation,temperature_2m,cloud_cover"}, ttl=900)
    h = j["hourly"]
    now_local = (datetime.now(timezone.utc) + timedelta(seconds=j.get("utc_offset_seconds", 0))).strftime("%Y-%m-%dT%H:00")
    i0 = next((i for i, t in enumerate(h["time"]) if t >= now_local), 0)
    sl = slice(i0, i0 + hours)
    return {"time": h["time"][sl], "ghi": [x or 0.0 for x in h["shortwave_radiation"][sl]],
            "temp": [x if x is not None else 25.0 for x in h["temperature_2m"][sl]],
            "cloud": h.get("cloud_cover", [None] * len(h["time"]))[sl], "source": "Open-Meteo hourly forecast"}


def pv_kw(ghi: float, temp: float, site: Dict[str, Any]) -> float:
    kwp = float(site.get("pv_kwp") or 0)
    if kwp <= 0:
        return 0.0
    tcell = temp + 0.03 * ghi
    p = kwp * ghi / 1000.0 * float(site.get("pv_pr") or PR) * (1 - 0.004 * max(0.0, tcell - 25.0))
    cap = site.get("inverter_kw")
    return max(0.0, min(p, cap) if cap else p)


def load_kw(load: Dict[str, Any], temp: float, hour: int) -> float:
    win = load.get("window")
    if win and hour not in win:
        return 0.0
    kw = float(load["kw"])
    if load.get("cooling"):                       # cooling duty rises with temperature: 10 % at 26 C ... 100 % at 38 C
        kw *= min(1.0, max(0.1, (temp - 26.0) / 12.0))
    return kw


def _simulate(site, hours, loads, soc_kwh, grid_ok, scheduled):
    cap = float(site.get("battery_kwh") or 0) if soc_kwh is not None else 0.0
    inv = float(site.get("inverter_kw") or 1e9)
    imp = float(site.get("grid_import_limit_kw") or 0)
    reserve = cap * float(site.get("battery_min_soc_pct", 20)) / 100.0
    floor = cap * HARD_FLOOR
    soc = soc_kwh or 0.0
    rows = []
    for k, (t, ghi, temp) in enumerate(hours):
        hour = int(t[11:13])
        pv = pv_kw(ghi, temp, site)
        todo = []
        for ld in loads:
            kw = load_kw(ld, temp, hour)
            if kw > 0:
                todo.append((ld.get("priority", 3), kw, ld["name"]))
        for name, hrs in scheduled.items():
            if k in hrs:
                ld = next(x for x in site["loads"] + site.get("_extra", []) if x["name"] == name)
                todo.append((ld.get("priority", 3), float(ld["kw"]), name))
        todo.sort()
        free = pv + (imp if grid_ok[k] else 0.0)
        br = min(max(0.0, soc - reserve) * EFF, inv)
        bc = min(max(0.0, soc - floor) * EFF, inv)
        served, shed, batt_out, demand = 0.0, [], 0.0, 0.0
        for prio, kw, name in todo:
            demand += kw
            if kw <= free:
                free -= kw; served += kw
                continue
            need = kw - free
            budget = bc if prio == 1 else br
            if need <= budget:
                batt_out += need; br -= need; bc -= need; free = 0.0; served += kw
            else:
                shed.append(name)
        from_free = served - batt_out
        pv_used = min(pv, from_free)
        import_used = max(0.0, from_free - pv_used)
        charge = 0.0
        if cap > 0:
            charge = max(0.0, min(pv - pv_used, inv, (cap - soc) / EFF))
            soc = min(cap, soc + charge * EFF - batt_out / EFF)
            soc = max(0.0, soc)
        crit = any(next((l for l in site["loads"] + site.get("_extra", []) if l["name"] == n), {}).get("priority", 3) == 1 for n in shed)
        rows.append({"time": t, "hour": hour, "temp_c": round(temp, 1), "ghi_wm2": round(ghi), "pv_kw": round(pv, 2),
                     "demand_kw": round(demand, 2), "served_kw": round(served, 2), "import_kw": round(import_used, 2),
                     "battery_kw": round(charge - batt_out / 1.0, 2), "soc_pct": round(100 * soc / cap, 1) if cap else None,
                     "shed": shed, "critical_shed": crit})
    return rows


def plan(site: Dict[str, Any], hourly: Dict[str, Any], state: Dict[str, Any], horizon: int = 24,
         outage_hours: Optional[List[int]] = None) -> Dict[str, Any]:
    n = min(horizon, len(hourly["time"]))
    hours = list(zip(hourly["time"][:n], hourly["ghi"][:n], hourly["temp"][:n]))
    warnings: List[str] = []
    soc_pct = state.get("soc_pct")
    cap = float(site.get("battery_kwh") or 0)
    soc_kwh = cap * soc_pct / 100.0 if (cap > 0 and soc_pct is not None) else None
    if cap > 0 and soc_kwh is None:
        warnings.append("Battery state of charge is unknown (no telemetry): the plan excludes the battery. Post telemetry to enable it.")
    grid_now = bool(state.get("grid_available", True))
    grid_ok = [grid_now and k not in (outage_hours or []) for k in range(n)]
    if outage_hours:
        warnings.append(f"Planning for a grid outage during step(s) {sorted(outage_hours)} of the horizon.")

    base = [l for l in site.get("loads", []) if not l.get("deferrable")]
    deferrable = [dict(l) for l in site.get("loads", []) if l.get("deferrable")]
    extra: List[Dict[str, Any]] = []

    # ---- water: tank level + heat-driven demand -> pump becomes a deferrable load
    water = None
    tank_l, dem, pump_lph, pump_kw = (site.get(k) for k in ("tank_l", "water_demand_lph", "pump_lph", "pump_kw"))
    if tank_l and dem and state.get("tank_pct") is not None:
        level = tank_l * state["tank_pct"] / 100.0
        use = [dem * (1 + 0.03 * max(0.0, h[2] - 30.0)) for h in hours]
        deficit = max(0.0, sum(use) - (level - 0.2 * tank_l))
        pump_hours = math.ceil(deficit / pump_lph) if pump_lph and deficit > 0 else 0
        empty_h = next((i + 1 for i in range(n) if level - sum(use[:i + 1]) <= 0), None)
        water = {"tank_pct_now": state["tank_pct"], "demand_24h_l": round(sum(use)), "hours_to_empty_without_pumping": empty_h,
                 "pump_hours_needed": pump_hours}
        if pump_kw and pump_lph and pump_hours:
            p = {"name": "water pump", "kw": pump_kw, "priority": 2, "deferrable": True, "run_hours": pump_hours}
            deferrable.append(p); extra.append(p)
        elif pump_hours:
            warnings.append("Tank will need refilling but pump_kw / pump_lph are not configured, so no pump schedule was made.")
    elif tank_l and dem:
        warnings.append("Tank level unknown (no telemetry): water plan skipped.")
    site = {**site, "_extra": extra}

    rows_a = _simulate(site, hours, base, soc_kwh, grid_ok, {})
    surplus = [max(0.0, r["pv_kw"] - r["demand_kw"]) for r in rows_a]
    scheduled: Dict[str, List[int]] = {}
    deferred_report = []
    for ld in sorted(deferrable, key=lambda x: x.get("priority", 3)):
        need = max(1, math.ceil(float(ld.get("run_hours") or 1)))
        win = ld.get("window")
        cand = [k for k in range(n) if not win or int(hours[k][0][11:13]) in win]
        cand.sort(key=lambda k: -surplus[k])
        pick = sorted(cand[:need])
        for k in pick:
            surplus[k] = max(0.0, surplus[k] - float(ld["kw"]))
        scheduled[ld["name"]] = pick
        sun = sum(1 for k in pick if rows_a[k]["pv_kw"] >= float(ld["kw"]) * 0.8)
        deferred_report.append({"load": ld["name"], "run_at": [hours[k][0] for k in pick], "on_surplus_pv_hours": sun, "requested_hours": need})
        if sun < len(pick):
            warnings.append(f"'{ld['name']}': only {sun} of {len(pick)} scheduled hour(s) are covered by surplus PV.")
    rows = _simulate(site, hours, base, soc_kwh, grid_ok, scheduled)

    tmax = max(h[2] for h in hours) if hours else None
    heat_hours = [r["time"] for r in rows if r["temp_c"] >= HEAT_WATCH_C]
    critical = [r["time"] for r in rows if r["critical_shed"]]
    shed_kwh = sum(r["demand_kw"] - r["served_kw"] for r in rows)
    dem_kwh = sum(r["demand_kw"] for r in rows)
    pv_kwh = sum(r["pv_kw"] for r in rows)
    socs = [r["soc_pct"] for r in rows if r["soc_pct"] is not None]
    summary = {"pv_kwh": round(pv_kwh, 1), "demand_kwh": round(dem_kwh, 1), "unserved_kwh": round(max(0.0, shed_kwh), 1),
               "grid_import_kwh": round(sum(r["import_kw"] for r in rows), 1), "min_soc_pct": min(socs) if socs else None,
               "critical_shortfall_hours": critical, "max_temp_c": round(tmax, 1) if tmax is not None else None,
               "heatwave": "severe" if tmax and tmax >= HEAT_SEVERE_C else "watch" if tmax and tmax >= HEAT_WATCH_C else "none",
               "pv_share_of_served_pct": round(100 * min(1.0, pv_kwh / max(1e-9, sum(r["served_kw"] for r in rows))), 1) if rows else None}
    return {"site": site.get("id"), "horizon_hours": n, "generated_from": hourly.get("source"), "rows": rows, "summary": summary,
            "deferred_loads": deferred_report, "water": water, "warnings": warnings,
            "recommendations": recommend(summary, rows, water, soc_pct)}


def recommend(summary, rows, water, soc_pct) -> List[str]:
    out: List[str] = []
    if summary["critical_shortfall_hours"]:
        out.append(f"CRITICAL: priority-1 load cannot be served at {', '.join(h[11:16] for h in summary['critical_shortfall_hours'][:4])}. "
                   "Start the backup source or reduce critical demand before then.")
    shed = sorted({n for r in rows for n in r["shed"]})
    if shed:
        hrs = [r["time"][11:16] for r in rows if r["shed"]]
        out.append(f"Shed or postpone {', '.join(shed)} around {hrs[0]}-{hrs[-1]} ({summary['unserved_kwh']} kWh unserved in the horizon).")
    if summary["heatwave"] != "none":
        out.append(f"Heat {summary['heatwave']}: temperature reaches {summary['max_temp_c']} C. Cooling demand is scaled up automatically; "
                   "pre-cool buildings before the peak and keep the battery above its reserve.")
        if soc_pct is not None and soc_pct < 80:
            out.append(f"Battery is at {soc_pct:.0f} %. Charge it fully from surplus PV (or grid) before the afternoon peak.")
    if water and water["hours_to_empty_without_pumping"] is not None and water["hours_to_empty_without_pumping"] <= 12:
        out.append(f"Water tank would run dry in about {water['hours_to_empty_without_pumping']} h without pumping; run the pump in the scheduled solar hours.")
    if not out:
        out.append("No shortfall expected in this horizon; keep monitoring telemetry.")
    return out
