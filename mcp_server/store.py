"""Persistencia mínima de los mocks: un archivo JSON por dominio.

La usan dos procesos: el server MCP (tools de negocio) y la API (endpoint de visión, que guarda
los documentos procesados). Por eso es un archivo y no un dict en memoria.

En Railway el disco es efímero: cada deploy vuelve a los datos semilla. Para un mock es suficiente.
"""

from __future__ import annotations

import json
import os
import re
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


DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]


def fecha_legible(iso: str) -> str:
    """'2026-11-04T10:00' → 'miércoles 4 de noviembre a las 10:00'. Los LLM se equivocan calculando el día
    de la semana: por eso las tools devuelven la fecha ya escrita como se dice en voz alta."""
    d = datetime.fromisoformat(iso) if "T" in iso else datetime.combine(date.fromisoformat(iso), time())
    texto = f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"
    return f"{texto} a las {d:%H:%M}" if "T" in iso else texto


def solo_digitos(valor: str) -> str:
    """'30.111.222' / '30 111 222' → '30111222'. Por voz y por LLM los datos llegan con formatos variados."""
    return re.sub(r"\D", "", valor or "")


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
