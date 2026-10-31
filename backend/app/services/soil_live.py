"""Soil properties for /insights/risk (SoilGrids with neighbour-pixel retry + farmer soil-type fallback). Fixes the 'no usable property values' failure: SoilGrids returns null for pixels that are
built-up/water, so we retry on neighbouring pixels (~250 m), and fall back to the farmer's soil type, labelled as such."""
import httpx
from .live_data import fetch, SourceError

TEXTURE_CLAY = {"sandy loam": 14, "sandy": 8, "sand": 6, "silty": 15, "silt": 15, "clay loam": 34, "clayey": 45,
                "clay": 50, "black": 52, "alluvial": 24, "red": 20, "laterite": 22, "loamy": 22, "loam": 22}
OFFSETS = [(0, 0), (0.0025, 0), (-0.0025, 0)]


def clay_from_soil_type(text):
    t = (text or "").lower()
    for key in sorted(TEXTURE_CLAY, key=len, reverse=True):   # longest match first ("sandy loam" before "loam")
        if key in t:
            return TEXTURE_CLAY[key]
    return None


async def _soilgrids(lat, lon):
    j = await fetch("soilgrids", "https://rest.isric.org/soilgrids/v2.0/properties/query", {
        "lon": round(lon, 5), "lat": round(lat, 5), "property": ["phh2o", "clay", "sand", "soc", "nitrogen"],
        "depth": ["0-5cm", "5-15cm"], "value": "mean"}, ttl=86400 * 7, retries=1, timeout=httpx.Timeout(30, connect=10))
    out = {}
    for layer in (j.get("properties") or {}).get("layers") or []:
        factor = (layer.get("unit_measure") or {}).get("d_factor") or 1
        v = [(d.get("values") or {}).get("mean") for d in layer.get("depths") or []]
        v = [x for x in v if x is not None]
        if v:
            out[layer.get("name")] = sum(v) / len(v) / factor
    return out


async def get_soil(lat, lon, soil_type=None):
    reason = "no value at this pixel"
    for k, (dlat, dlon) in enumerate(OFFSETS):
        try:
            out = await _soilgrids(lat + dlat, lon + dlon)
        except SourceError as e:       # provider down/slow: do not keep hammering it
            reason = e.msg
            break
        if out:
            return {"ph": out.get("phh2o"), "clay_pct": out.get("clay"), "sand_pct": out.get("sand"),
                    "soc_g_kg": out.get("soc"), "nitrogen_g_kg": out.get("nitrogen"), "kind": "model-estimate",
                    "source": "ISRIC SoilGrids 250 m" + (" (neighbouring pixel ~250 m away)" if k else ""),
                    "note": "Modelled soil properties, not a live soil-moisture or lab measurement."}
    clay = clay_from_soil_type(soil_type)
    if clay is not None:
        return {"clay_pct": clay, "kind": "user-input", "source": f"farmer-reported soil type '{soil_type}'",
                "note": f"SoilGrids unavailable ({reason}); clay % is a typical value for this texture, not a measurement."}
    raise SourceError("soilgrids", f"no usable soil values ({reason}) and no soil type on the farm profile")
