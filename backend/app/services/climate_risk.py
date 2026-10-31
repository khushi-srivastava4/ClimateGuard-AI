"""Crop-aware climate-risk engine for /insights/risk (soil moisture, normals, river discharge). Pure functions, no I/O, unit-tested.
Scores are 0-100 per hazard, each with traceable evidence tagged to a source id (S1..S5)."""
from statistics import median

from .crop_profiles import CROPS  # noqa: F401

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
PAST = 30          # days of history requested; index PAST in the daily arrays == today
EFFECTIVE_RAIN = 0.8   # share of rainfall assumed useful to the crop (rest = runoff/evaporation)


def clamp(x, lo=0.0, hi=1.0): return max(lo, min(hi, x))
def level(s): return "low" if s < 25 else "moderate" if s < 50 else "high" if s < 75 else "severe"
def vals(xs): return [x for x in xs if x is not None]
def total(xs): return sum(vals(xs))
def E(text, *src): return {"text": text, "src": list(src)}


def blend(parts):
    parts = [(w, s) for w, s in parts if s is not None]
    return sum(w * s for w, s in parts) / sum(w for w, _ in parts) if parts else 0.0


def daily_means(times, values):
    acc = {}
    for t, v in zip(times, values):
        if v is not None:
            acc.setdefault(t[:10], []).append(v)
    return {d: sum(v) / len(v) for d, v in acc.items()}


def hydraulics(soil):
    """Pedotransfer from clay %: wilting point and field capacity in m3/m3 (approximate)."""
    clay = (soil or {}).get("clay_pct")
    assumed = clay is None
    clay = 20.0 if assumed else clay
    return {"pwp": 0.035 + 0.0045 * clay, "fc": 0.11 + 0.0065 * clay, "assumed": assumed}


def windows(flags, dates, minlen=2):
    out, i = [], 0
    while i < len(flags):
        if flags[i]:
            j = i
            while j + 1 < len(flags) and flags[j + 1]:
                j += 1
            if j - i + 1 >= minlen:
                out.append({"start": dates[i], "end": dates[j], "days": j - i + 1})
            i = j + 1
        else:
            i += 1
    return sorted(out, key=lambda w: -w["days"])


def assess(fc, flood, clim, soil, crop, stage=None):
    d, P = fc["daily"], PAST
    t = d["time"]
    if len(t) < P + 8:
        raise ValueError("forecast too short to assess")
    tmax, pr, et0 = d["temperature_2m_max"], d["precipitation_sum"], d["et0_fao_evapotranspiration"]
    pprob = d.get("precipitation_probability_max") or [None] * len(t)
    h = fc.get("hourly", {})
    sm0 = daily_means(h.get("time", []), h.get("soil_moisture_0_to_7cm", []))
    sm1 = daily_means(h.get("time", []), h.get("soil_moisture_7_to_28cm", []))
    st = daily_means(h.get("time", []), h.get("soil_temperature_6cm", []))
    hy = hydraulics(soil)
    pwp, fcap = hy["pwp"], hy["fc"]

    def blend_sm(day):
        a, b = sm0.get(day), sm1.get(day)
        return a if b is None else b if a is None else (a * 7 + b * 21) / 28

    aw = []
    for day in t:
        v = blend_sm(day)
        aw.append(None if v is None else (v - pwp) / (fcap - pwp))
    H = slice(P, P + 14)
    aw_now = aw[P]
    aw_min = min(vals(aw[H])) if vals(aw[H]) else None

    month = MONTHS[int(t[P][5:7]) - 1]
    norm = ((clim or {}).get("PRECTOTCORR") or {}).get(month)       # mm/day, 30-yr normal
    norm30, norm14 = (norm * 30, norm * 14) if norm is not None else (None, None)
    rain30, rain14, rain7 = total(pr[:P]), total(pr[H]), total(pr[P:P + 7])
    demand14 = total(et0[H]) * crop["kc"]
    kc = crop["kc"]
    sensitive = any(k in (stage or "").lower() for k in ("flower", "grain", "fruit", "anthesis", "boll", "tassel"))
    heat_thr = crop["heat"] - (2 if sensitive else 0)
    stage_note = f", lowered 2°C for {stage} stage" if sensitive else ""

    # ---- drought / water stress
    unmet = clamp((demand14 - rain14 * EFFECTIVE_RAIN) / demand14) if demand14 > 1 else 0.0
    s_soil = clamp((0.5 - aw_min) / 0.5) if aw_min is not None else None
    s_def = clamp(1 - rain30 / norm30) if norm30 and norm30 > 5 else None
    drought = 100 * blend([(0.4, s_soil), (0.25, s_def), (0.35, unmet)])
    ev_d = [E(f"Crop water demand next 14 days ≈ {demand14:.0f} mm (ET0 × Kc {kc}) vs forecast rain {rain14:.0f} mm", "S1")]
    if aw_now is not None:
        ev_d.append(E(f"Modelled root-zone available water {aw_now * 100:.0f}% today, lowest {aw_min * 100:.0f}% in next 14 days"
                      + (" (soil texture assumed)" if hy["assumed"] else ""), "S1", "S4"))
    if s_def is not None:
        ev_d.append(E(f"Last 30 days rain {rain30:.0f} mm vs 30-year normal {norm30:.0f} mm for {month.title()}", "S1", "S3"))

    # ---- heat stress
    fut = vals(tmax[H])
    heat_days = sum(1 for x in fut if x >= heat_thr)
    mx = max(fut) if fut else None
    heat = 100 * (0.6 * clamp(heat_days / 5) + 0.4 * clamp((mx - heat_thr + 3) / 8)) if mx is not None else 0.0
    ev_h = [E(f"{heat_days} of next 14 days reach ≥{heat_thr}°C (crop stress threshold{stage_note}); hottest day {mx:.0f}°C", "S1")] if mx is not None else []

    # ---- flood / waterlogging
    roll3 = [total(pr[i:i + 3]) for i in range(P, P + 12)]
    peak3 = max(roll3)
    peak_day = t[P + roll3.index(peak3)]
    s_rain = clamp(peak3 / (1.25 * crop["waterlog"]))
    s_river, ratio = 0.0, None
    if flood and flood.get("daily"):
        ft, fv = flood["daily"]["time"], flood["daily"].get("river_discharge") or []
        past = [v for dd, v in zip(ft, fv) if v is not None and dd < t[P]]
        futr = [v for dd, v in zip(ft, fv) if v is not None and dd >= t[P]]
        if len(past) >= 10 and futr and median(past) > 0.01:
            ratio = max(futr) / median(past)
            s_river = clamp((ratio - 1.5) / 3.5)
    floodscore = 100 * max(s_rain, s_river)
    if aw_now is not None and aw_now > 1.0 and peak3 > 20:
        floodscore = min(100, floodscore * 1.1)
    ev_f = [E(f"Heaviest 3-day rain {peak3:.0f} mm around {peak_day} vs crop waterlogging limit ~{crop['waterlog']} mm", "S1")]
    if ratio is not None:
        ev_f.append(E(f"Nearby river discharge forecast peaks at {ratio:.1f}× its 60-day median", "S2"))

    # ---- unseasonal rain
    unseason, ev_u = 0.0, []
    if norm14 is not None:
        r = rain14 / norm14 if norm14 > 0.5 else 9.0
        excess = rain14 - norm14
        unseason = 100 * clamp(excess / max(40, 1.5 * norm14)) * clamp(r - 1)
        ev_u.append(E(f"Forecast rain {rain14:.0f} mm in 14 days vs 30-year normal {norm14:.0f} mm", "S1", "S3"))

    risks = {k: {"score": int(round(min(100, v))), "level": level(v), "evidence": ev}
             for k, v, ev in (("drought", drought, ev_d), ("heat", heat, ev_h),
                              ("flood", floodscore, ev_f), ("unseasonal_rain", unseason, ev_u))}

    # ---- irrigation need (net of effective rain), two weeks
    weekly = []
    for w in (0, 1):
        s = slice(P + 7 * w, P + 7 * w + 7)
        weekly.append(round(max(0.0, total(et0[s]) * kc - total(pr[s]) * EFFECTIVE_RAIN), 1))

    # ---- sowing and dry (harvest/drying) windows
    idx = range(P, P + 14)
    sow_ok = []
    for i in idx:
        ok = (st.get(t[i]) is not None and crop["sow"][0] <= st[t[i]] <= crop["sow"][1]
              and total(pr[i:i + 3]) <= 25 and (tmax[i] is None or tmax[i] <= crop["heat"] + 3)
              and (aw[i] is None or 0.3 <= aw[i] <= 1.05))
        sow_ok.append(ok)
    dry_ok = [(pr[i] or 0) <= 1.0 and (pprob[i] is None or pprob[i] <= 40) for i in idx]
    dates = [t[i] for i in idx]

    return {
        "risks": risks,
        "water": {"weekly_irrigation_mm": weekly, "balance_14d_mm": round(rain14 * EFFECTIVE_RAIN - demand14, 1),
                  "assumption": f"{int(EFFECTIVE_RAIN * 100)}% of rain counted as effective"},
        "sowing_windows": windows(sow_ok, dates, 2),
        "dry_windows": windows(dry_ok, dates, 3),
        "actions": actions(risks, crop, weekly, peak_day),
        "soil_model": {"wilting_point": round(pwp, 3), "field_capacity": round(fcap, 3), "texture_assumed": hy["assumed"]},
        "thresholds": {"heat_c": heat_thr, "waterlog_mm_3d": crop["waterlog"]},
        "peak_rain": {"mm": round(peak3, 1), "day": peak_day},
        "series": {"dates": t[P - 7:], "past_len": 7, "pprob": pprob[P - 7:], "tmax": tmax[P - 7:], "precip": pr[P - 7:], "et0": et0[P - 7:],
                   "avail_water_pct": [None if a is None else round(a * 100) for a in aw[P - 7:]]},
    }


def actions(risks, crop, weekly, peak_day):
    out = []
    r = lambda k: risks[k]["score"]
    if r("drought") >= 50:
        out.append(f"Plan about {weekly[0]:.0f} mm irrigation this week and {weekly[1]:.0f} mm next week; prioritise critical growth stages and mulch to cut evaporation.")
    if r("heat") >= 50:
        out.append("Irrigate early morning or evening, avoid spraying and transplanting 11:00-16:00, and postpone top-dressing until the hot spell passes.")
    if r("flood") >= 50:
        out.append(f"Clear drainage channels before {peak_day}; hold fertiliser and pesticide spray for 48 h around heavy rain; harvest mature produce early.")
    if r("unseasonal_rain") >= 50:
        out.append("Cover or move harvested produce under shelter; scout for fungal disease after rain; delay sowing until fields can be worked.")
    if not out:
        out.append("No hazard above moderate in the next 14 days; follow the normal crop calendar and re-check in 2-3 days.")
    return out


def grid_scores(daily):
    """Generic (crop-agnostic) 7-day hazard scores for one grid cell, used for the micro-location heat map."""
    tmax, pr, et0 = vals(daily["temperature_2m_max"]), daily["precipitation_sum"], vals(daily["et0_fao_evapotranspiration"])
    heat = 100 * clamp((max(tmax) - 34) / 9) if tmax else 0
    rain3 = max(total(pr[i:i + 3]) for i in range(max(1, len(pr) - 2)))
    rain = 100 * clamp(rain3 / 90)
    dem = total(et0) * 0.8
    dry = 100 * clamp((dem - total(pr)) / dem) if dem > 1 else 0
    return {"heat": round(heat), "rain": round(rain), "dry": round(dry),
            "overall": round(max(heat, rain, dry * 0.7)), "max_temp": max(tmax) if tmax else None, "rain_7d": round(total(pr), 1)}
