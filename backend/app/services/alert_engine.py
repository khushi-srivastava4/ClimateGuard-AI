"""Alert generation with de-duplication. Pure functions: persist the returned alerts with your existing DB layer."""
from datetime import date

LABEL = {"drought": "Drought / water stress", "heat": "Heat stress", "flood": "Heavy rain / waterlogging",
         "unseasonal_rain": "Unseasonal rain"}
ORDER = {"low": 0, "moderate": 1, "high": 2, "severe": 3}


def build_alerts(farm_id, assessment, enabled=True, threshold=60, today=None):
    if not enabled:
        return []
    wk = (today or date.today()).isocalendar()[:2]
    out = []
    for hz, r in assessment["risks"].items():
        if r["score"] < threshold:
            continue
        out.append({"farm_id": farm_id, "hazard": hz, "severity": r["level"], "score": r["score"],
                    "title": f"{LABEL.get(hz, hz)}: {r['level']} ({r['score']}/100)",
                    "message": " ".join(e["text"] + "." for e in r["evidence"][:2]),
                    # same hazard + same level in the same ISO week = one alert; escalation to a higher level re-alerts
                    "dedupe_key": f"{farm_id}:{hz}:{r['level']}:{wk[0]}-W{wk[1]}"})
    return sorted(out, key=lambda a: -ORDER[a["severity"]])


def only_new(alerts, existing_keys):
    seen = set(existing_keys)
    return [a for a in alerts if a["dedupe_key"] not in seen]
