"""Application configuration and environment settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class Settings:
    """Centralized environment configuration for the application."""

    def __init__(self) -> None:
        self.APP_NAME = os.getenv("APP_NAME", "ClimateGuard AI")
        self.ENV = os.getenv("ENV", "development")
        default_data_dir = Path(__file__).resolve().parents[1] / "data"
        configured_data_dir = os.getenv("DATA_DIR", "").strip() or str(default_data_dir)
        self.DATA_DIR = Path(configured_data_dir).expanduser().resolve()
        self.CORS_ORIGINS: List[str] = [
            item.strip()
            for item in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
            if item.strip()
        ]
        self.CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))
        self.HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
        self.ADVISE_TIMEOUT = float(os.getenv("ADVISE_TIMEOUT", "80"))
        self.MANDI_API_KEY = os.getenv("MANDI_API_KEY", "")
        self.GNANI_API_KEY = os.getenv("GNANI_API_KEY", "")
        self.SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
        self.MANDI_RESOURCE_ID = (
            os.getenv("MANDI_RESOURCE_ID", "").strip()
            or "9ef84268-d588-465a-a308-a864a43d0070"
        )
        self.MANDI_CACHE = os.getenv("MANDI_CACHE", "")
        self.HTTP_USER_AGENT = os.getenv("HTTP_USER_AGENT", "KavachHackathon/1.0")
        self.OPS_DB = os.getenv("OPS_DB", "")
        self.OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org")
        self.RELIEF_AUTOPILOT_MINUTES = float(os.getenv("RELIEF_AUTOPILOT_MINUTES", "0") or 0)
        self.RELIEF_MIN_LEVEL = os.getenv("RELIEF_MIN_LEVEL", "high")
        self.ALLOWED_SUPPLIER_HOSTS = [
            item.strip().lower().rstrip(".")
            for item in os.getenv("ALLOWED_SUPPLIER_HOSTS", "").split(",")
            if item.strip()
        ]
        self.ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
        self.RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "120"))
        self.RATE_LIMIT_HEAVY_PER_MIN = int(os.getenv("RATE_LIMIT_HEAVY_PER_MIN", "20"))
        self.TRUST_PROXY = os.getenv("TRUST_PROXY", "0").strip() == "1"
        self.MAX_REQUEST_BODY_BYTES = int(os.getenv("MAX_REQUEST_BODY_BYTES", str(1024 * 1024)))
        self.LLM_PROVIDER = os.getenv("LLM_PROVIDER", "GEMINI").upper()
                # LLM_API_KEY wins; otherwise use the chosen provider's own variable, so GEMINI_API_KEY alone is enough
        provider_key_env = {"GEMINI": "GEMINI_API_KEY", "OPENAI": "OPENAI_API_KEY", "ANTHROPIC": "ANTHROPIC_API_KEY", "GROQ": "GROQ_API_KEY"}.get(self.LLM_PROVIDER)
        self.LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip() or (os.getenv(provider_key_env, "").strip() if provider_key_env else "")
        default_model = {
            "OPENAI": "gpt-4o-mini",
            "ANTHROPIC": "claude-3-haiku-20240307",
            "GROQ": "llama-3.1-8b-instant",
            "GEMINI": "gemini-2.5-flash",
        }.get(self.LLM_PROVIDER, "gpt-4o-mini")
        self.LLM_MODEL = os.getenv("LLM_MODEL", "").strip() or default_model
        self.LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
        self.LLM_CONNECT_TIMEOUT = float(os.getenv("LLM_CONNECT_TIMEOUT", "10"))
        self.LLM_READ_TIMEOUT = float(os.getenv("LLM_READ_TIMEOUT", "60"))
        self.LLM_WRITE_TIMEOUT = float(os.getenv("LLM_WRITE_TIMEOUT", "10"))
        self.LLM_POOL_TIMEOUT = float(os.getenv("LLM_POOL_TIMEOUT", "5"))
        # Optional backup providers, tried in this order when the primary one is rate-limited or down.
        self.BACKUP_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
        self.BACKUP_ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
        self.BACKUP_GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
        self.BACKUP_GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        self.BACKUP_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
        self.BACKUP_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
        self.BACKUP_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        self.BACKUP_OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


settings = Settings()
