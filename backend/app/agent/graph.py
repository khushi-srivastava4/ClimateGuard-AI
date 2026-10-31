"""LangGraph orchestration for ClimateGuard AI."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any, Dict, TypedDict

import httpx

from app.agent.prompts import build_system_prompt
from app.config import settings
from app.models.mandi import MandiData
from app.models.weather import WeatherData
from app.services import llm_router
from app.services.mandi_service import get_mandi
from app.services.risk_engine import compute_risk
from app.services.soil_service import get_soil
from app.services.weather_service import get_weather
from app.utils.cache import cache

logger = logging.getLogger(__name__)

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover
    StateGraph = None
    END = START = "__stub__"


class AgentState(TypedDict, total=False):
    latitude: float
    longitude: float
    language: str
    crop: str
    mandicriteria: str
    market_state: str
    market_district: str
    weather: Dict[str, Any]
    soil: Dict[str, Any]
    mandi: Dict[str, Any]
    risk: Dict[str, Any]
    advice: str
    sources: list[str]
    advice_status: str
    advice_provider: str


async def fetch_weather_node(state: AgentState) -> AgentState:
    try:
        weather = await get_weather(state["latitude"], state["longitude"])
        state["weather"] = {
            "latitude": state["latitude"],
            "longitude": state["longitude"],
            "max_temp": weather.max_temp,
            "precipitation_total": weather.precipitation_total,
            "daily": [item.model_dump(mode="json") for item in weather.daily],
            "timezone": weather.timezone,
            "source": weather.source,
            "retrieved_at": weather.retrieved_at.isoformat() if weather.retrieved_at else None,
            "error": None,
        }
    except Exception as exc:
        logger.warning("Weather data unavailable (%s).", type(exc).__name__)
        state["weather"] = {
            "latitude": state["latitude"],
            "longitude": state["longitude"],
            "max_temp": None,
            "precipitation_total": None,
            "daily": [],
            "source": "Open-Meteo",
            "retrieved_at": None,
            "error": f"Weather provider request failed ({type(exc).__name__}).",
        }
    return state


async def fetch_soil_node(state: AgentState) -> AgentState:
    try:
        soil = await get_soil(state["latitude"], state["longitude"])
        state["soil"] = {
            "latitude": state["latitude"],
            "longitude": state["longitude"],
            "properties": soil.properties,
            "property_units": soil.property_units,
            "depth": soil.depth,
            "source": soil.source,
            "retrieved_at": soil.retrieved_at.isoformat() if soil.retrieved_at else None,
            "error": soil.error,
            "interpretation": "SoilGrids properties are modelled estimates, not current field-moisture measurements.",
        }
    except Exception as exc:
        logger.warning("Soil data unavailable (%s).", type(exc).__name__)
        state["soil"] = {
            "latitude": state["latitude"],
            "longitude": state["longitude"],
            "properties": {},
            "source": "ISRIC SoilGrids",
            "retrieved_at": None,
            "error": f"Soil provider request failed ({type(exc).__name__}).",
            "interpretation": "No soil estimates are available for this location.",
        }
    return state


async def fetch_mandi_node(state: AgentState) -> AgentState:
    try:
        mandi = await get_mandi(
            state["latitude"],
            state["longitude"],
            state.get("crop", "wheat"),
            state.get("mandicriteria", ""),
            state.get("market_state"),
            state.get("market_district"),
        )
        state["mandi"] = _mandi_payload(mandi)
    except Exception as exc:
        logger.warning("Mandi data unavailable (%s).", type(exc).__name__)
        state["mandi"] = _mandi_payload(
            MandiData(
                crop=state.get("crop", "wheat"),
                market="N/A",
                error=f"Mandi provider request failed ({type(exc).__name__}).",
            )
        )
    return state


PROVIDER_BUDGET_SECONDS = 28.0


def _timeout_payload(key: str, state: AgentState) -> Dict[str, Any]:
    if key == "weather":
        return {"latitude": state["latitude"], "longitude": state["longitude"], "max_temp": None,
                "precipitation_total": None, "daily": [], "source": "Open-Meteo", "retrieved_at": None,
                "error": "Weather provider did not answer in time."}
    if key == "soil":
        return {"latitude": state["latitude"], "longitude": state["longitude"], "properties": {},
                "source": "ISRIC SoilGrids", "retrieved_at": None, "error": "Soil provider did not answer in time.",
                "interpretation": "No soil estimates are available for this location."}
    return _mandi_payload(MandiData(crop=state.get("crop", "wheat"), market="N/A",
                                    error="Mandi provider did not answer in time."))


async def _bounded(key: str, branch, state: AgentState) -> AgentState:
    """Run one provider branch with its own deadline; a timeout becomes an explicit error, not a failed request."""
    try:
        return await asyncio.wait_for(branch(dict(state)), timeout=PROVIDER_BUDGET_SECONDS)
    except asyncio.TimeoutError:
        logger.warning("%s provider exceeded its %.0f s budget.", key, PROVIDER_BUDGET_SECONDS)
        return {key: _timeout_payload(key, state)}


async def fetch_provider_data_node(state: AgentState) -> AgentState:
    """Fetch independent provider data concurrently, preserving graph state updates."""
    branches = [
        _bounded("weather", lambda s: fetch_weather_node(s), state),
        _bounded("soil", lambda s: fetch_soil_node(s), state),
    ]
    if state.get("mandicriteria"):
        branches.append(_bounded("mandi", lambda s: fetch_mandi_node(s), state))
    results = await asyncio.gather(*branches)
    updates: AgentState = {}
    for key in ("weather", "soil", "mandi"):
        for result in results:
            if key in result:
                updates[key] = result[key]
                break
    return updates


def _mandi_payload(mandi: MandiData) -> Dict[str, Any]:
    return {
        "average_price": mandi.average_price,
        "market": mandi.market,
        "error": mandi.error,
        "source": mandi.source,
        "retrieved_at": mandi.retrieved_at.isoformat() if mandi.retrieved_at else None,
        "prices": [
            {"date": item.date, "price": item.price, "market": item.market, "commodity": item.commodity, "unit": item.unit}
            for item in mandi.prices
        ],
    }


async def compute_risk_node(state: AgentState) -> AgentState:
    state["risk"] = compute_risk(
        weather=state.get("weather", {}),
        soil=state.get("soil", {}),
        mandi=state.get("mandi", {}),
        crop=state.get("crop", "wheat"),
    ).to_payload()
    return state


async def generate_advice_node(state: AgentState) -> AgentState:
    language = state.get("language", "en")
    crop = state.get("crop", "wheat")
    prompt = build_system_prompt(language, crop)
    data_summary = json.dumps({
        "weather": state.get("weather", {}),
        "soil": state.get("soil", {}),
        "mandi": state.get("mandi", {}),
        "risk": state.get("risk", {}),
    }, default=str)
    text, status, provider = await _advise_text(prompt, data_summary, language, state)
    state["advice"] = text
    state["advice_status"] = status          # generated | fallback | unavailable
    state["advice_provider"] = provider      # the engine that really wrote the text
    state["sources"] = state["risk"].get("sources", [])
    return state


async def _advise_text(prompt: str, data_summary: str, language: str, state: AgentState) -> tuple[str, str, str]:
    """Primary LLM -> backup LLMs -> rule-based summary. Never labels fallback text as AI-generated."""
    key = "advice:" + hashlib.sha256(f"{language}|{prompt}|{data_summary}".encode()).hexdigest()
    hit = cache.get(key)          # identical request within 30 min: do not spend quota again
    if isinstance(hit, dict) and hit.get("text"):
        return hit["text"], "generated", hit.get("provider", "cache")

    unavailable = _advisory_unavailable(language)
    text = await _call_llm(prompt, data_summary, language)
    if text != unavailable:
        cache.set(key, {"text": text, "provider": settings.LLM_PROVIDER.lower()}, ttl_seconds=1800)
        return text, "generated", settings.LLM_PROVIDER.lower()
    try:
        res = await llm_router.generate(data_summary, prompt, skip=[settings.LLM_PROVIDER.lower()])
        cache.set(key, {"text": res["text"], "provider": res["provider"]}, ttl_seconds=1800)
        return res["text"], "generated", res["provider"]
    except llm_router.AllProvidersFailed as exc:
        logger.warning("No backup LLM answered: %s", exc)
    rules = _rules_advice(state.get("risk", {}), language)
    return (rules, "fallback", "rules") if rules else (unavailable, "unavailable", "none")


def _rules_advice(risk: Dict[str, Any], language: str) -> str:
    reasons = [r for r in risk.get("reasons", []) if isinstance(r, str)][:4]
    if not reasons:
        return ""
    head = (
        "यह नियम-आधारित सारांश है (AI मॉडल उपलब्ध नहीं था)।"
        if language.lower() == "hi"
        else "Rule-based summary (no AI model was available)."
    )
    tail = (
        "खेत की स्थिति देखकर ही सिंचाई या छिड़काव करें; बड़े निर्णय से पहले कृषि विज्ञान केंद्र से पूछें।"
        if language.lower() == "hi"
        else "Check field conditions before irrigating or spraying, and confirm costly actions with your local Krishi Vigyan Kendra."
    )
    return "\n".join([head, *[f"- {r}" for r in reasons], tail])


async def _call_llm(prompt: str, data_summary: str, language: str) -> str:
    provider = settings.LLM_PROVIDER.upper()
    api_key = settings.LLM_API_KEY
    if not api_key:
        logger.warning("LLM advisory unavailable: no API key configured.")
        return _advisory_unavailable(language)

    model = settings.LLM_MODEL
    if provider == "GEMINI":
        endpoint = (
            "https://generativelanguage.googleapis.com/"
            f"v1beta/models/{model}:generateContent"
        )
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }
        body = {
            "systemInstruction": {"parts": [{"text": prompt}]},
            "contents": [{"role": "user", "parts": [{"text": data_summary}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1000},
        }
    elif provider == "ANTHROPIC":
        endpoint = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "max_tokens": 1000,
            "system": prompt,
            "messages": [{"role": "user", "content": data_summary}],
        }
    elif provider in ("OPENAI", "GROQ"):
        endpoint = (
            "https://api.groq.com/openai/v1/chat/completions"
            if provider == "GROQ"
            else "https://api.openai.com/v1/chat/completions"
        )
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": data_summary},
            ],
            "temperature": 0.2,
        }
    else:
        logger.error("LLM advisory unavailable: unsupported provider %s.", provider)
        return _advisory_unavailable(language)

    timeout = _llm_timeout()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(2):
                response = await client.post(endpoint, headers=headers, json=body)
                if (
                    response.status_code == 429
                    and _is_quota_error(_api_error_message(response, api_key))
                ):
                    break
                if response.status_code not in {429, 500, 502, 503, 504} or attempt == 1:
                    break

                retry_after = response.headers.get("Retry-After", "")
                try:
                    delay = min(max(float(retry_after), 0.0), 1.0)
                except ValueError:
                    delay = 0.5
                logger.warning(
                    "%s API returned transient HTTP %s; retrying (%s/2).",
                    provider,
                    response.status_code,
                    attempt + 2,
                )
                await asyncio.sleep(delay)

        if response.is_error:
            message = _api_error_message(response, api_key)
            logger.error("%s API returned HTTP %s: %s", provider, response.status_code, message)
            return _advisory_unavailable(language)

        data = response.json()
        if provider == "GEMINI":
            text = _extract_gemini_text(data)
        elif provider == "ANTHROPIC":
            blocks = data.get("content", []) if isinstance(data, dict) else []
            text = "".join(
                block.get("text", "")
                for block in blocks
                if isinstance(block, dict) and block.get("type") == "text"
            )
        else:
            choices = data.get("choices", []) if isinstance(data, dict) else []
            first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
            message = first_choice.get("message", {})
            text = message.get("content", "") if isinstance(message, dict) else ""

        if isinstance(text, str) and text.strip():
            return text.strip()
        logger.error("%s returned an empty advisory response.", provider)
    except httpx.ConnectTimeout:
        logger.error("%s connection timed out before reaching the API.", provider)
    except httpx.ReadTimeout:
        logger.error("%s response timed out while waiting for the API.", provider)
    except httpx.WriteTimeout:
        logger.error("%s request timed out while sending data to the API.", provider)
    except httpx.PoolTimeout:
        logger.error("%s request timed out while waiting for an HTTP connection.", provider)
    except httpx.TimeoutException as exc:
        logger.error("%s request timed out (%s).", provider, type(exc).__name__)
    except httpx.ConnectError as exc:
        logger.error("%s connection failed (%s).", provider, type(exc).__name__)
    except httpx.RequestError as exc:
        logger.error("%s request failed (%s).", provider, type(exc).__name__)
    except (ValueError, TypeError, KeyError) as exc:
        message = str(exc).replace(api_key, "[redacted]") if api_key else str(exc)
        logger.error("%s returned an invalid response: %s", provider, " ".join(message.split())[:200])

    return _advisory_unavailable(language)


def _advisory_unavailable(language: str) -> str:
    if language.lower() == "hi":
        return (
            "AI सलाह अभी उपलब्ध नहीं है। कृपया डैशबोर्ड के जोखिम "
            "संकेतकों और उपलब्ध मौसम डेटा की समीक्षा करें।"
        )
    return (
        "AI-generated advisory is unavailable. Please review the "
        "dashboard's risk indicators and available data."
    )


def _llm_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        connect=min(max(settings.LLM_CONNECT_TIMEOUT, 0.1), 8.0),
        read=min(max(settings.LLM_READ_TIMEOUT, 0.1), 15.0),
        write=min(max(settings.LLM_WRITE_TIMEOUT, 0.1), 5.0),
        pool=min(max(settings.LLM_POOL_TIMEOUT, 0.1), 2.0),
    )


def _api_error_message(response: httpx.Response, api_key: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "API returned a non-JSON error response."

    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    message = error.get("message") if isinstance(error, dict) else None
    if not isinstance(message, str) or not message.strip():
        return "API did not provide an error message."
    sanitized = message.replace(api_key, "[redacted]") if api_key else message
    return " ".join(sanitized.split())[:300]


def _is_quota_error(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in ("quota", "resource_exhausted", "billing"))


def _extract_gemini_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise ValueError("Gemini response root is not an object.")

    feedback = payload.get("promptFeedback")
    if isinstance(feedback, dict) and feedback.get("blockReason"):
        raise ValueError("Gemini blocked the prompt.")

    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Gemini response contained no candidates.")

    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise ValueError("Gemini candidate is not an object.")
    if candidate.get("finishReason") in {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}:
        raise ValueError("Gemini blocked the candidate.")

    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise ValueError("Gemini candidate contained no content parts.")

    text = "".join(
        part["text"]
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    )
    if not text.strip():
        raise ValueError("Gemini candidate contained no text.")
    return text

def build_graph() -> Any:
    if StateGraph is None:
        class _FallbackGraph:
            async def ainvoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
                return {**state, "advice": "Advisory unavailable without LangGraph.", "sources": []}

        return _FallbackGraph()

    builder = StateGraph(AgentState)
    builder.add_node("fetch_provider_data", fetch_provider_data_node)
    builder.add_node("score_risk", compute_risk_node)
    builder.add_node("compose_advice", generate_advice_node)

    builder.add_edge(START, "fetch_provider_data")
    builder.add_edge("fetch_provider_data", "score_risk")
    builder.add_edge("score_risk", "compose_advice")
    builder.add_edge("compose_advice", END)

    return builder.compile()
