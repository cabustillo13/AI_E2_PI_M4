"""Persistencia mínima de los mocks: un archivo JSON por dominio.

La usan dos procesos: el server MCP (tools de negocio) y la API (endpoint de visión, que guarda
los documentos procesados). Por eso es un archivo y no un dict en memoria.

En Railway el disco es efímero: cada deploy vuelve a los datos semilla. Para un mock es suficiente.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import date, datetime, time
from pathlib import Path
from typing import Callable, Iterator

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / ".data"))


def today() -> date:
    """'Hoy' del negocio. OPSVOICE_TODAY=2026-11-02 fija la fecha (tests y evals reproducibles)."""
    fixed = os.getenv("OPSVOICE_TODAY")
    return date.fromisoformat(fixed) if fixed else date.today()


def now() -> datetime:
    """'Ahora' del negocio. Con fecha fija, son las 08:00 de ese día."""
    if os.getenv("OPSVOICE_TODAY"):
        return datetime.combine(today(), time(8, 0))
    return datetime.now()


def _path(domain: str) -> Path:
    return DATA_DIR / f"{domain}.json"


def load(domain: str, seed: Callable[[], dict]) -> dict:
    path = _path(domain)
    if not path.exists():
        save(domain, seed())
    return json.loads(path.read_text(encoding="utf-8"))


def save(domain: str, data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(domain).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_path(domain))  # escritura atómica: nunca queda un JSON a medio escribir


@contextmanager
def edit(domain: str, seed: Callable[[], dict]) -> Iterator[dict]:
    data = load(domain, seed)
    yield data
    save(domain, data)


def reset(domain: str) -> None:
    _path(domain).unlink(missing_ok=True)
