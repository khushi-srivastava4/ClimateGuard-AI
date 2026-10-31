"""Advisory generation: grounded prompt -> LLM router -> numeric grounding check -> one self-correction -> rules fallback.
The response always states which engine wrote the text."""
import json
from . import grounding, llm_router
from .action_planner import plan_actions

LANGS = {"en": "English", "hi": "Hindi", "bn": "Bengali", "mr": "Marathi", "ta": "Tamil", "te": "Telugu",
         "gu": "Gujarati", "kn": "Kannada", "pa": "Punjabi", "ml": "Malayalam", "or": "Odia",
         "as": "Assamese", "ur": "Urdu"}
SRC = {"S1": "Open-Meteo forecast", "S2": "GloFAS river discharge (Open-Meteo)", "S3": "NASA POWER 30-year normals",
       "S4": "soil data", "S5": "NOAA ONI (ENSO)", "S6": "Agmarknet mandi prices"}
SYSTEM = ("You are ClimateGuard, an agricultural climate-risk advisor for farmers. Use ONLY the figures in DATA; never "
          "invent numbers, prices or dates. Cite sources inline like [S1]. If a field is missing or marked unavailable, say that "
          "plainly and do not fill the gap. Risk scores are heuristic indicators, not probabilities of crop loss. Soil values are "
          "modelled estimates, not live soil-moisture readings. Write in the requested language in plain words. Begin with the single "
          "most urgent action and its date window, then 3-5 short bullets (what, when, how much), then one line on confidence and "
          "data gaps. At most 170 words. Advise confirming costly actions with the local Krishi Vigyan Kendra.")


def build_summary(a, crop_id, stage, soil, enso, mandi, place, actions):
    return {"crop": crop_id, "growth_stage": stage, "place": place,
            "risks": {k: {"score": v["score"], "level": v["level"], "evidence": [e["text"] + " [" + ",".join(e["src"]) + "]" for e in v["evidence"]]}
                      for k, v in a["risks"].items()},
            "irrigation_mm_per_week": a["water"]["weekly_irrigation_mm"], "water_note": a["water"]["assumption"],
            "sowing_windows": a["sowing_windows"][:2], "dry_windows": a["dry_windows"][:2],
            "planned_actions": [{"date": x["date"], "title": x["title"]} for x in actions[:6]],
            "soil": soil, "enso": enso, "mandi": mandi, "source_ids": SRC}


def rules_text(summary, language):
    r = summary["risks"]
    top = sorted(r.items(), key=lambda kv: -kv[1]["score"])[:3]
    lines = ["Rule-based advisory (no AI model was available)."]
    lines += [f"- {k.replace('_', ' ').title()}: {v['level']} ({v['score']}/100). {v['evidence'][0] if v['evidence'] else ''}" for k, v in top]
    lines += [f"- {x['date']}: {x['title']}" for x in summary["planned_actions"][:4]]
    if summary.get("mandi"):
        m = summary["mandi"]
        lines.append(f"- Mandi median price ₹{m['median_modal']:.0f}/quintal across {m['markets']} markets ({m['scope']}) [S6]")
    return "\n".join(lines)


async def advise(summary, language="en", question=None, history=None):
    past = "".join(f"{h['role'].upper()}: {str(h['content'])[:400]}\n" for h in (history or [])[-6:] if h.get("role") in ("user", "assistant"))
    prompt = (f"Language: {LANGS.get(language, 'English')}\n" + (f"Conversation so far:\n{past}" if past else "") + f"Farmer's question: {question or 'Give my advisory for the next two weeks.'}\n"
              f"DATA:\n{json.dumps(summary, ensure_ascii=False)}")
    try:
        res = await llm_router.generate(prompt, SYSTEM)
    except llm_router.AllProvidersFailed as e:
        return {"advisory": rules_text(summary, language), "generated_by": {"provider": "rules", "model": None, "fallback": True},
                "grounding": None, "attempts": e.attempts}
    g = grounding.check(res["text"], summary)
    if g["unverified"]:          # self-correction round
        try:
            fix = await llm_router.generate(prompt + f"\n\nYour draft used figures that are not in DATA: {g['unverified']}. Rewrite using only DATA figures, or remove them.", SYSTEM, use_cache=False)
            g2 = grounding.check(fix["text"], summary)
            if g2["score"] >= g["score"]:
                res, g = fix, {**g2, "self_corrected": True}
        except llm_router.AllProvidersFailed:
            pass
    return {"advisory": res["text"], "generated_by": {"provider": res["provider"], "model": res["model"], "fallback": False, "cached": res.get("cached", False)},
            "grounding": g, "attempts": res["attempts"]}
