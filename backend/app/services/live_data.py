"""Live data connectors. Every function hits a real API; none return canned data.
Resilience: retries with backoff, TTL cache, stale-cache fallback (flagged), per-source status."""
import asyncio, os, re, time
import httpx


class SourceError(Exception):
    def __init__(self, source, msg):
        super().__init__(f"{source}: {msg}")
        self.source, self.msg = source, msg


STATUS: dict = {}     # source -> {state: live|stale|unavailable, latency_ms, error, ts}
_cache: dict = {}
_client = None


def _http():
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            headers={"User-Agent": os.getenv("HTTP_USER_AGENT", "KavachHackathon/1.0")},
            follow_redirects=True)
    return _client


async def fetch(source, url, params=None, ttl=600, retries=2, timeout=15.0, text=False):
    key = url + repr(sorted((params or {}).items()))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    last = None
    for i in range(retries + 1):
        t0 = time.time()
        try:
            r = await _http().get(url, params=params, timeout=timeout)
            r.raise_for_status()
            data = r.text if text else r.json()
            STATUS[source] = {"state": "live", "latency_ms": int((time.time() - t0) * 1000), "ts": int(time.time())}
            _cache[key] = (time.time(), data)
            return data
        except Exception as e:
            last = e
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (400, 401, 403, 404, 422):
                break
            await asyncio.sleep(0.5 * (i + 1))
    err = (str(last)[:140] or type(last).__name__)
    if hit:  # real data, just old: serve it but say so
        STATUS[source] = {"state": "stale", "error": err, "ts": int(hit[0])}
        return hit[1]
    STATUS[source] = {"state": "unavailable", "error": err, "ts": int(time.time())}
    raise SourceError(source, err)


async def forecast(lat, lon):
    return await fetch("open-meteo/forecast", "https://api.open-meteo.com/v1/forecast", {
        "latitude": lat, "longitude": lon, "timezone": "auto", "past_days": 30, "forecast_days": 16,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,et0_fao_evapotranspiration,"
                 "wind_gusts_10m_max,precipitation_probability_max",
        "hourly": "soil_moisture_0_to_7cm,soil_moisture_7_to_28cm,soil_temperature_6cm"}, ttl=900)


async def grid_forecast(points):
    j = await fetch("open-meteo/forecast", "https://api.open-meteo.com/v1/forecast", {
        "latitude": ",".join(f"{a:.3f}" for a, _ in points),
        "longitude": ",".join(f"{b:.3f}" for _, b in points),
        "daily": "temperature_2m_max,precipitation_sum,et0_fao_evapotranspiration",
        "forecast_days": 7, "timezone": "auto"}, ttl=900)
    return j if isinstance(j, list) else [j]


async def flood(lat, lon):  # GloFAS river discharge
    return await fetch("open-meteo/flood", "https://flood-api.open-meteo.com/v1/flood", {
        "latitude": lat, "longitude": lon, "daily": "river_discharge",
        "past_days": 60, "forecast_days": 16}, ttl=3600)


async def climatology(lat, lon):  # NASA POWER 30-yr monthly normals
    j = await fetch("nasa-power", "https://power.larc.nasa.gov/api/temporal/climatology/point", {
        "parameters": "PRECTOTCORR,T2M_MAX", "community": "AG", "longitude": round(lon, 3),
        "latitude": round(lat, 3), "format": "JSON"}, ttl=86400 * 30, timeout=25)
    p = j["properties"]["parameter"]
    return {k: {m: v for m, v in d.items() if v is not None and v > -900} for k, d in p.items()}


async def enso():  # NOAA CPC Oceanic Nino Index
    txt = await fetch("noaa-cpc/oni", "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt", ttl=86400, text=True)
    rows = [l.split() for l in txt.splitlines() if re.match(r"^\s*[A-Z]{3}\s+\d{4}\s", l)]
    if not rows:
        raise SourceError("noaa-cpc/oni", "unexpected file format")
    seas, yr, _, anom = rows[-1][:4]
    a = float(anom)
    return {"season": f"{seas} {yr}", "oni": a, "phase": "El Niño" if a >= 0.5 else "La Niña" if a <= -0.5 else "Neutral"}
