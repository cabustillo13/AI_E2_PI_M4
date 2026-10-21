"""Carga el 'domain pack': domains/<id>.md = frontmatter YAML (metadata) + markdown (prompt y KB).

Un solo archivo por dominio es la fuente de verdad del comportamiento del agente: lo usa el backend
para armar el system prompt; la KB y la metadata sirven para configurar el agente en ElevenLabs.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from mcp_server.store import today

DOMAINS_DIR = Path(__file__).resolve().parent.parent / "domains"
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
KB_HEADING = "# Base de conocimiento"


@dataclass(frozen=True)
class Domain:
    id: str
    meta: dict
    body: str  # markdown sin frontmatter

    @property
    def knowledge_base(self) -> str:
        """Sección '# Base de conocimiento' (se sube también a la KB de ElevenLabs)."""
        _, _, kb = self.body.partition(KB_HEADING)
        return f"{KB_HEADING}{kb}".strip() if kb else ""

    def system_prompt(self) -> str:
        """Prompt del dominio + reglas comunes. Se arma en cada turno para que 'hoy' esté al día."""
        hoy = today()
        comun = (DOMAINS_DIR / "_comun.md").read_text(encoding="utf-8")
        comun = comun.replace("{hoy}", hoy.isoformat()).replace("{dia_semana}", DIAS[hoy.weekday()])
        return f"{self.body.strip()}\n\n{comun.strip()}"


def parse(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise ValueError("El domain pack debe empezar con un frontmatter YAML entre '---'.")
    _, front, body = text.split("---", 2)
    return yaml.safe_load(front) or {}, body


@lru_cache
def load_domain(domain_id: str) -> Domain:
    path = DOMAINS_DIR / f"{domain_id}.md"
    if not path.exists():
        raise ValueError(f"No existe el domain pack {path}")
    meta, body = parse(path.read_text(encoding="utf-8"))
    for key in ("id", "empresa", "agente", "idioma", "primer_mensaje", "documento_vision", "presupuesto_usd_conversacion"):
        if key not in meta:
            raise ValueError(f"{path.name}: falta '{key}' en el frontmatter")
    return Domain(id=meta["id"], meta=meta, body=body)
