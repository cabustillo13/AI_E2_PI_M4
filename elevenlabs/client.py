"""Cliente HTTP mínimo para la API de ElevenLabs Agents (lo usan los scripts de esta carpeta y evals/)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import ROOT  # noqa: E402  (carga el .env)

BASE_URL = os.getenv("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io")


def client() -> httpx.Client:
    key = os.getenv("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("Falta ELEVENLABS_API_KEY en el .env")
    return httpx.Client(base_url=BASE_URL, headers={"xi-api-key": key}, timeout=60)


def check(resp: httpx.Response) -> dict:
    if resp.status_code >= 400:
        sys.exit(f"ElevenLabs {resp.request.method} {resp.request.url.path} → {resp.status_code}: {resp.text[:800]}")
    return resp.json() if resp.content else {}


AGENTS_DIR = ROOT / "elevenlabs" / "agents"
