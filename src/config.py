"""Configuración por variables de entorno (ver .env.example). Nada de secretos en el código."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass
class Settings:
    domain: str = field(default_factory=lambda: _env("DOMAIN", "clinica"))
    api_key: str = field(default_factory=lambda: _env("OPSVOICE_API_KEY"))

    # Modelos en formato "proveedor:modelo". El orden de la cadena es el orden de fallback.
    # Por defecto solo OpenAI: sumar anthropic:... a la cadena es opcional (requiere AnthropicProvider).
    llm_chain: tuple[str, ...] = field(default_factory=lambda: tuple(
        m.strip() for m in _env("LLM_CHAIN", "openai:gpt-4.1-mini,openai:gpt-4o-mini").split(",") if m.strip()
    ))
    llm_cheap: str = field(default_factory=lambda: _env("LLM_CHEAP", "openai:gpt-4.1-nano"))
    vision_model: str = field(default_factory=lambda: _env("VISION_MODEL", "openai:gpt-4.1-mini"))

    # Harness
    first_token_timeout_s: float = field(default_factory=lambda: float(_env("FIRST_TOKEN_TIMEOUT_S", "6")))
    max_tool_iterations: int = field(default_factory=lambda: int(_env("MAX_TOOL_ITERATIONS", "5")))
    rate_limit_per_minute: int = field(default_factory=lambda: int(_env("RATE_LIMIT_PER_MINUTE", "30")))
    budget_degrade_ratio: float = field(default_factory=lambda: float(_env("BUDGET_DEGRADE_RATIO", "0.7")))

    # Agente de ElevenLabs que se embebe en la demo pública (GET /demo)
    elevenlabs_agent_id: str = field(default_factory=lambda: _env("ELEVENLABS_AGENT_ID"))


settings = Settings()
