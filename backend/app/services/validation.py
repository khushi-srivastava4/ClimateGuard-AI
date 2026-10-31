"""Evidence pipeline for the heuristic risk scores.

We do NOT claim the scores are validated. Instead every risk assessment is logged, farmers/field staff can report what
actually happened (including "nothing happened"), and once enough labelled outcomes exist this module computes Brier score,
AUC and a reliability table per hazard. Until then the status says exactly how many labels are missing.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services import ops_store as S
from app.services.swarm import haversine_km

HAZARDS = ("drought", "heat", "flood", "unseasonal_rain")
EVENTS = HAZARDS + ("none",)
MIN_LABELS, MIN_POSITIVES = 30, 5
MATCH_KM, MAX_LEAD_DAYS = 20.0, 14


def log_prediction(lat: float, lon: float, crop: str, risks: Dict[str, Dict[str, Any]]) -> None:
    scores = {k: v["score"] for k, v in risks.items() if k in HAZARDS and isinstance(v.get("score"), (int, float))}
    if scores:
        S.add_event("prediction", f"{round(lat, 1)},{round(lon, 1)}", {"lat": lat, "lon": lon, "crop": crop, "scores": scores})


def add_outcome(lat: float, lon: float, crop: str, event: str, observed_date: str, severity: Optional[int] = None) -> Dict[str, Any]:
    if event not in EVENTS:
        raise ValueError(f"event must be one of {EVENTS}")
    day = datetime.strptime(observed_date, "%Y-%m-%d").replace(hour=12, tzinfo=timezone.utc).timestamp()
    if day > time.time() + 86400:
        raise ValueError("observed_date cannot be in the future")
    rec = {"lat": lat, "lon": lon, "crop": crop, "event": event, "observed_date": observed_date, "severity": severity, "observed_ts": day}
    S.add_event("outcome", None, rec)
    return rec


def auc(pairs: List[tuple]) -> Optional[float]:
    pos = [s for s, y in pairs if y == 1]
    neg = [s for s, y in pairs if y == 0]
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 3)


def build_pairs(preds: List[Dict[str, Any]], outs: List[Dict[str, Any]]) -> Dict[str, List[tuple]]:
    pairs: Dict[str, List[tuple]] = {h: [] for h in HAZARDS}
    for o in outs:
        cands = [p for p in preds
                 if haversine_km((p["lat"], p["lon"]), (o["lat"], o["lon"])) <= MATCH_KM
                 and 86400 <= o["observed_ts"] - p["ts"] <= MAX_LEAD_DAYS * 86400]
        if not cands:
            continue
        p = max(cands, key=lambda x: x["ts"])           # latest forecast issued at least a day ahead
        for h in HAZARDS:
            if h not in p["scores"]:
                continue
            if o["event"] == h:
                pairs[h].append((p["scores"][h] / 100.0, 1))
            elif o["event"] == "none":
                pairs[h].append((p["scores"][h] / 100.0, 0))
    return pairs


def metrics(pairs: Dict[str, List[tuple]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for h, pr in pairs.items():
        n, pos = len(pr), sum(y for _, y in pr)
        if n < MIN_LABELS or pos < MIN_POSITIVES or n - pos < MIN_POSITIVES:
            out[h] = {"status": "insufficient labels", "labelled": n, "events": pos, "needs": f">={MIN_LABELS} labels with >={MIN_POSITIVES} events and >={MIN_POSITIVES} non-events"}
            continue
        brier = sum((s - y) ** 2 for s, y in pr) / n
        bins = []
        for lo in (0.0, 0.25, 0.5, 0.75):
            b = [(s, y) for s, y in pr if lo <= s < lo + 0.25 or (lo == 0.75 and s == 1.0)]
            if b:
                bins.append({"score_range": f"{int(lo * 100)}-{int((lo + 0.25) * 100)}", "n": len(b), "mean_score": round(sum(s for s, _ in b) / len(b), 2), "event_rate": round(sum(y for _, y in b) / len(b), 2)})
        out[h] = {"status": "evaluated", "labelled": n, "events": pos, "brier": round(brier, 3), "auc": auc(pr), "reliability": bins}
    return out


def status() -> Dict[str, Any]:
    preds, outs = S.events("prediction", limit=5000), S.events("outcome", limit=5000)
    m = metrics(build_pairs(preds, outs))
    evaluated = [h for h, v in m.items() if v["status"] == "evaluated"]
    return {"status": "partially validated" if evaluated else "unvalidated",
            "model": "rule-based heuristic risk engine (no trained ML model)",
            "reason": (f"Evaluated against {len(outs)} field-reported outcomes for: {', '.join(evaluated)}." if evaluated else
                       f"{len(preds)} assessments logged and {len(outs)} outcomes reported; at least {MIN_LABELS} labelled outcomes per hazard "
                       "are needed before accuracy can be measured. No crop-loss or yield labels exist, so scores are not calibrated probabilities."),
            "predictions_logged": len(preds), "outcomes_reported": len(outs), "hazards": m}
