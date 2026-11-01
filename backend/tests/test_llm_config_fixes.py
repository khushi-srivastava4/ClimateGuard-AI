import importlib, os
from unittest.mock import patch
import app.config as config
from app.services import llm_router


def settings_with(env):
    with patch.dict(os.environ, env, clear=False):
        for k in ("LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY"):
            if k not in env: os.environ.pop(k, None)
        return config.Settings()


def test_gemini_api_key_alone_is_enough_for_the_primary_provider():
    s = settings_with({"LLM_PROVIDER": "GEMINI", "GEMINI_API_KEY": "g-key"})
    assert s.LLM_API_KEY == "g-key"
    with patch.object(llm_router, "settings", s):
        names = [p["name"] for p in llm_router.providers()]
    assert names == ["gemini"]                                    # same key is not listed twice


def test_second_gemini_key_from_another_project_is_used_as_backup():
    s = settings_with({"LLM_PROVIDER": "GEMINI", "LLM_API_KEY": "primary", "GEMINI_API_KEY": "second"})
    with patch.object(llm_router, "settings", s):
        names = [p["name"] for p in llm_router.providers()]
        assert names == ["gemini", "gemini-backup"]
        async def go():
            seen = []
            async def fake(p, prompt, system):
                seen.append(p["name"])
                if p["name"] == "gemini": raise llm_router.ProviderError("HTTP 429 (quota or rate limit)", 429, None)
                return "ok"
            with patch.object(llm_router, "_call", fake):
                llm_router.COOLDOWN.clear(); llm_router.CACHE.clear()
                r = await llm_router.generate("p", "s", skip=["gemini"])   # exactly how graph.py calls it
            return r, seen
        import asyncio
        r, seen = asyncio.run(go())
    assert r["provider"] == "gemini-backup" and seen == ["gemini-backup"]
