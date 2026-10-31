"""Guardrail: every number with a unit (mm, °C, %, ₹) in the advisory must exist in the data given to the model."""
import json, re, unicodedata

PAT = re.compile(r"(?:(?:₹|Rs\.?)\s*(\d[\d,]*(?:\.\d+)?))|(?:(\d[\d,]*(?:\.\d+)?)\s*(?:mm|°C|°|%|मिमी|মিমি|மி\.மீ))")
NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _ascii_digits(s):
    return "".join(str(unicodedata.digit(c)) if c.isdigit() and not c.isascii() else c for c in s)


def check(text, data):
    corpus = []
    for m in NUM.findall(json.dumps(data, ensure_ascii=False)):
        v = float(m); corpus += [v, v * 100]          # also match 0.45 reported as 45 %
    claims = []
    for m in PAT.finditer(_ascii_digits(text)):
        claims.append(float((m.group(1) or m.group(2)).replace(",", "")))
    bad = [c for c in claims if not any(abs(c - k) <= max(0.6, 0.06 * abs(k)) for k in corpus)]
    n = len(claims)
    return {"checked": n, "unverified": sorted(set(bad)), "score": round(1 - len(bad) / n, 2) if n else 1.0}
