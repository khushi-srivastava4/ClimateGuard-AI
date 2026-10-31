"""Agmarknet mandi summary for /insights/risk. Fixes ReadTimeout: long read timeout, retries, and a disk cache that is
served (clearly labelled stale) when the portal is slow. Never invents a price."""
import json, os, time
from app.config import settings
from pathlib import Path
import httpx
from .live_data import fetch, SourceError

URL = "https://api.data.gov.in/resource/" + settings.MANDI_RESOURCE_ID
CACHE = Path(os.getenv("MANDI_CACHE", Path(__file__).resolve().parents[2] / "data" / "mandi_cache.json"))


def _load():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(key, value):
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        d = _load(); d[key] = {"ts": int(time.time()), "value": value}
        CACHE.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


def summarise(recs, scope, commodity):
    recs = [r for r in recs if str(r.get("modal_price", "")).replace(".", "", 1).isdigit()]
    if not recs:
        return None
    prices = sorted(float(r["modal_price"]) for r in recs)
    top = sorted(recs, key=lambda r: -float(r["modal_price"]))[:5]
    return {"scope": scope, "commodity": commodity, "unit": "INR/quintal", "markets": len(recs),
            "median_modal": prices[len(prices) // 2], "min_modal": prices[0], "max_modal": prices[-1],
            "latest_arrival_date": max(r.get("arrival_date", "") for r in recs),
            "best_markets": [{"market": r.get("market"), "district": r.get("district"), "modal": float(r["modal_price"])} for r in top]}


async def get_mandi(state, commodity):
    key = settings.MANDI_API_KEY
    if not key:
        raise SourceError("data.gov.in/agmarknet", "MANDI_API_KEY not set in .env")
    ck = f"{state or '*'}|{commodity}"
    try:
        for st in ([state] if state else []) + [None]:
            p = {"api-key": key, "format": "json", "limit": 100, "filters[commodity]": commodity}
            if st:
                p["filters[state.keyword]"] = st
            j = await fetch("data.gov.in/agmarknet", URL, p, ttl=3600, retries=2, timeout=httpx.Timeout(75, connect=15))
            out = summarise(j.get("records", []), st or "India (no records for state)", commodity)
            if out:
                _save(ck, out)
                return out
        raise SourceError("data.gov.in/agmarknet", f"no current mandi records for {commodity}")
    except SourceError as e:
        old = _load().get(ck)
        if old:
            return {**old["value"], "stale": True, "cached_at": old["ts"], "stale_reason": e.msg}
        raise
