#!/usr/bin/env python3
"""ClimateGuard edge agent: runs on a Raspberry Pi / gateway next to the inverter, battery and pumps.

Pure standard library (no pip install). Each cycle it
  1. reads your sensors   (--sensor-cmd prints JSON like {"soc_pct": 62, "tank_pct": 41, "load_kw": 3.2, "grid_available": true})
  2. posts that telemetry to the server and fetches the new 24 h plan
  3. applies the CURRENT hour's decision through --actuator-cmd (receives JSON on stdin: shed list, deferrable loads to run)
If the server is unreachable it keeps working: it reuses the cached plan while it is fresh, and otherwise falls back to a
local fail-safe (shed priority >= 3 loads when battery is at or below its reserve). It never invents sensor readings:
if the sensor command fails, nothing is posted and the actuators are left unchanged.

Example:
  python edge_agent.py --server http://192.168.1.10:8000 --site clinic \
      --sensor-cmd "python read_inverter.py" --actuator-cmd "python apply_relays.py" --interval 300
"""
import argparse, json, os, subprocess, sys, time, urllib.request
from datetime import datetime

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "edge_cache.json")


def http(method, url, body=None, timeout=15):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "null")


def read_sensors(cmd):
    try:
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        data = json.loads(out.stdout)
        return data if isinstance(data, dict) else None
    except Exception as e:
        print(f"[edge] sensor read failed: {e}", file=sys.stderr)
        return None


def load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(obj):
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def decide(plan, site, telemetry, now):
    """Pick the plan row for the current hour; fall back to a local rule when no fresh plan exists."""
    if plan and now - plan.get("fetched", 0) < 6 * 3600:
        hour = now_hour(now)
        row = next((r for r in plan["rows"] if r["hour"] == hour), None)
        if row:
            run = [d["load"] for d in plan.get("deferred_loads", []) if any(t[11:13] == f"{hour:02d}" for t in d["run_at"])]
            return {"source": "server plan", "shed": row["shed"], "run_deferrable": run, "hour": hour}
    soc, reserve = (telemetry or {}).get("soc_pct"), (site or {}).get("battery_min_soc_pct", 20)
    shed = []
    if soc is not None and soc <= reserve and site:
        shed = [l["name"] for l in site.get("loads", []) if l.get("priority", 3) >= 3]
    return {"source": "local fail-safe (no fresh plan)", "shed": shed, "run_deferrable": [], "hour": now_hour(now)}


def now_hour(ts):
    return datetime.fromtimestamp(ts).hour


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True); ap.add_argument("--site", required=True)
    ap.add_argument("--sensor-cmd", required=True); ap.add_argument("--actuator-cmd", default="")
    ap.add_argument("--interval", type=int, default=300); ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    base = a.server.rstrip("/")
    while True:
        cache = load_cache()
        t = read_sensors(a.sensor_cmd)
        if t:
            try:
                http("POST", f"{base}/grid/telemetry", {"site_id": a.site, **{k: t.get(k) for k in ("soc_pct", "tank_pct", "load_kw", "pv_kw")},
                                                       "grid_available": bool(t.get("grid_available", True))})
            except Exception as e:
                print(f"[edge] telemetry upload failed (will retry): {e}", file=sys.stderr)
        try:
            cache["site"] = next((s for s in http("GET", f"{base}/grid/sites") if s["id"] == a.site), cache.get("site"))
            plan = http("GET", f"{base}/grid/plan/{a.site}", timeout=60)
            plan["fetched"] = time.time(); cache["plan"] = plan; save_cache(cache)
            print(f"[edge] new plan, {len(plan['rows'])} h, warnings: {plan['warnings']}")
        except Exception as e:
            print(f"[edge] server unreachable ({e}); using cached plan or fail-safe", file=sys.stderr)
        decision = decide(cache.get("plan"), cache.get("site"), t, time.time())
        print(f"[edge] decision: {json.dumps(decision)}")
        if a.actuator_cmd and t is not None:          # no sensor data => leave actuators unchanged
            try:
                subprocess.run(a.actuator_cmd, shell=True, input=json.dumps(decision), text=True, timeout=30)
            except Exception as e:
                print(f"[edge] actuator command failed: {e}", file=sys.stderr)
        if a.once:
            break
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
