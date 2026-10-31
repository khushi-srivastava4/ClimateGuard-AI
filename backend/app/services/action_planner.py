"""Field-action planner v2: dated, crop-specific, conditional actions built from the risk assessment.
Replaces the repetitive 'check soil' actions: an action only appears when the forecast justifies it."""
import hashlib, math
from datetime import date, timedelta
from .crop_profiles import CROPS


def _shift(d, n, floor):
    return max(floor, (date.fromisoformat(d) + timedelta(days=n)).isoformat())


def plan_actions(a, crop_id, stage=None):
    crop, stage = CROPS[crop_id], (stage or "").lower()
    s = a["series"]; k = s["past_len"]
    dates, tmax, pr = s["dates"][k:], s["tmax"][k:], s["precip"][k:]
    thr, acts = a["thresholds"]["heat_c"], []

    def add(d, cat, pri, title, detail):
        key = hashlib.md5(f"{cat}|{d}|{title}".encode()).hexdigest()[:10]
        if not any(x["key"] == key for x in acts):
            acts.append({"key": key, "date": d, "category": cat, "priority": pri, "title": title, "detail": detail})

    harvest = any(x in stage for x in ("harvest", "mature", "ripen"))
    presow = (not stage) or any(x in stage for x in ("sow", "prepar", "fallow", "pre-"))

    if presow:
        if a["sowing_windows"]:
            w = a["sowing_windows"][0]
            add(w["start"], "sowing", "high", f"Sow {crop['label']} between {w['start']} and {w['end']}",
                f"Soil temperature, 3-day rain and soil moisture all sit inside the crop's sowing limits for {w['days']} days.")
        else:
            add(dates[0], "sowing", "medium", f"Hold off sowing {crop['label']}",
                "No 2-day stretch in the next 14 days meets the soil-temperature, rain and moisture limits. Re-check in 3 days.")

    if not harvest:
        for w in (0, 1):
            need = a["water"]["weekly_irrigation_mm"][w]
            if need < 15:
                continue
            cand = [i for i in range(7 * w, min(7 * w + 7, len(dates))) if (pr[i] or 0) <= 2]
            n = min(3, math.ceil(need / 30), len(cand))
            if n == 0:
                continue
            picks = sorted({cand[round(j * (len(cand) - 1) / max(1, n - 1))] for j in range(n)}) if n > 1 else [cand[0]]
            for i in picks:
                add(dates[i], "irrigation", "high" if need >= 40 else "medium", f"Irrigate about {need / len(picks):.0f} mm",
                    f"Week {w + 1} crop water demand exceeds effective rain by {need:.0f} mm. Irrigate early morning or evening.")

    pk = a["peak_rain"]
    if pk["mm"] >= 0.6 * a["thresholds"]["waterlog_mm_3d"]:
        add(_shift(pk["day"], -1, dates[0]), "drainage", "high", "Clear drainage channels and field bunds",
            f"About {pk['mm']:.0f} mm of rain is forecast over 3 days from {pk['day']} (waterlogging limit for this crop ≈ {a['thresholds']['waterlog_mm_3d']} mm).")
        add(_shift(pk["day"], -1, dates[0]), "spray", "medium", "Postpone fertiliser and pesticide spray until 2 days after the rain",
            "Spray and fertiliser are washed off or leach in heavy rain.")

    i = 0
    while i < len(dates):
        if tmax[i] is not None and tmax[i] >= thr:
            j = i
            while j + 1 < len(dates) and tmax[j + 1] is not None and tmax[j + 1] >= thr:
                j += 1
            add(dates[i], "heat", "high", f"Heat spell {dates[i]} to {dates[j]}: shift work to early morning and evening",
                f"Maximum temperature reaches {max(tmax[i:j + 1]):.0f}°C against the crop's {thr}°C stress threshold. Avoid spraying and transplanting at midday.")
            i = j + 1
        else:
            i += 1

    if harvest and a["dry_windows"]:
        w = a["dry_windows"][0]
        add(w["start"], "harvest", "high", f"Harvest and dry produce between {w['start']} and {w['end']}",
            f"{w['days']} consecutive days with almost no rain forecast.")

    if any(x in stage for x in ("veg", "tiller", "seedling")):
        for i in range(len(dates) - 2):
            if sum(x or 0 for x in pr[i:i + 3]) <= 10 and (tmax[i] or 0) < thr:
                add(dates[i], "nutrition", "medium", "Apply top-dress fertiliser",
                    "A mostly dry 3-day stretch lets the fertiliser settle without runoff.")
                break

    if not acts:
        add(_shift(dates[0], 3, dates[0]), "review", "low", "No action needed; re-check the forecast",
            "No hazard crosses the planning thresholds in the next 14 days.")
    return sorted(acts, key=lambda x: (x["date"], x["priority"] != "high"))[:10]
