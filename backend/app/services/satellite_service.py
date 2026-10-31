"""Real Sentinel-2 NDVI from public Cloud-Optimised GeoTIFFs (Element84 Earth Search STAC, no API key).
Reads only a small window around the point, masks clouds/shadow with the SCL band, returns an NDVI time series.
Requires: rasterio, numpy. Runs in worker threads so it never blocks the event loop."""
import asyncio, math
from datetime import datetime, timedelta, timezone
import httpx
from .live_data import SourceError

STAC = "https://earth-search.aws.element84.com/v1/search"
GOOD_SCL = (4, 5)              # vegetation, bare soil
CLOUDY_SCL = (3, 8, 9, 10)     # shadow, cloud medium/high, thin cirrus


def bbox(lat, lon, half_km=0.5):
    dlat = half_km / 111.32
    dlon = half_km / (111.32 * max(0.2, math.cos(math.radians(lat))))
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def _scene_ndvi(item, box):
    import numpy as np, rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds
    A, shape = item["assets"], (64, 64)

    def read(key, resampling):
        with rasterio.open(A[key]["href"]) as ds:
            win = from_bounds(*transform_bounds("EPSG:4326", ds.crs, *box), transform=ds.transform)
            return ds.read(1, window=win, out_shape=shape, resampling=resampling, boundless=True, fill_value=0).astype("float32")

    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", AWS_NO_SIGN_REQUEST="YES",
                      GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="1", GDAL_HTTP_TIMEOUT="25"):
        red, nir, scl = read("red", Resampling.bilinear), read("nir", Resampling.bilinear), read("scl", Resampling.nearest)
    rb = (A["red"].get("raster:bands") or [{}])[0]
    scale, offset = rb.get("scale", 0.0001), rb.get("offset", -0.1)   # processing baseline >= 04.00 uses -0.1
    r, n = red * scale + offset, nir * scale + offset
    ndvi = (n - r) / np.maximum(n + r, 1e-6)
    valid = np.isin(scl, GOOD_SCL) & (red > 0)
    cloudy = np.isin(scl, CLOUDY_SCL).mean()
    if valid.mean() < 0.2:
        return None            # too cloudy / no data in the window: skip rather than guess
    v = ndvi[valid]
    return {"date": item["properties"]["datetime"][:10], "ndvi_mean": round(float(v.mean()), 3),
            "ndvi_p10": round(float(np.percentile(v, 10)), 3), "ndvi_p90": round(float(np.percentile(v, 90)), 3),
            "valid_fraction": round(float(valid.mean()), 2), "cloud_fraction": round(float(cloudy), 2),
            "scene_cloud_cover_pct": item["properties"].get("eo:cloud_cover"), "scene": item["id"]}


async def ndvi_series(lat, lon, days=60, half_km=0.5, max_scenes=8, max_cloud=70):
    box = bbox(lat, lon, half_km)
    end = datetime.now(timezone.utc)
    body = {"collections": ["sentinel-2-l2a"], "bbox": box, "limit": 30,
            "datetime": f"{(end - timedelta(days=days)):%Y-%m-%d}T00:00:00Z/{end:%Y-%m-%d}T23:59:59Z",
            "query": {"eo:cloud_cover": {"lt": max_cloud}}, "sortby": [{"field": "properties.datetime", "direction": "desc"}]}
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(STAC, json=body)
            r.raise_for_status()
            feats = r.json().get("features", [])
    except Exception as e:
        raise SourceError("earth-search/stac", str(e)[:140] or type(e).__name__)
    best = {}                                    # one scene per date (overlapping tiles): least cloud wins
    for f in feats:
        d = f["properties"]["datetime"][:10]
        if d not in best or f["properties"].get("eo:cloud_cover", 100) < best[d]["properties"].get("eo:cloud_cover", 100):
            best[d] = f
    items = sorted(best.values(), key=lambda f: f["properties"]["datetime"], reverse=True)[:max_scenes]
    res = await asyncio.gather(*[asyncio.to_thread(_scene_ndvi, it, box) for it in items], return_exceptions=True)
    pts = sorted([x for x in res if isinstance(x, dict)], key=lambda x: x["date"])
    errs = [f"{type(x).__name__}: {str(x)[:80]}" for x in res if isinstance(x, Exception)]
    if not pts:
        raise SourceError("sentinel-2", "no cloud-free scenes in window" + (f"; read errors: {errs[:2]}" if errs else ""))
    trend = None
    if len(pts) >= 2:
        d = pts[-1]["ndvi_mean"] - pts[0]["ndvi_mean"]
        trend = {"change": round(d, 3), "direction": "greening" if d > 0.05 else "declining" if d < -0.05 else "stable",
                 "from": pts[0]["date"], "to": pts[-1]["date"]}
    return {"area_km": round(2 * half_km, 2), "series": pts, "trend": trend, "skipped_scenes": len(items) - len(pts),
            "source": "Copernicus Sentinel-2 L2A via Earth Search STAC",
            "caveat": "NDVI averages everything inside the box (neighbouring fields, roads, trees); it is not a per-field crop-health measurement."}
