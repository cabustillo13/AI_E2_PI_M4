"""Observabilidad: trazas en Langfuse (si hay claves) + métricas en memoria para /metrics.

En voz importa la latencia p95, no el promedio: una respuesta lenta corta la conversación.
Medimos TTFT (tiempo hasta el primer texto que se puede hablar) por turno.
"""

from __future__ import annotations

import contextlib
import os
import statistics
from collections import Counter, deque
from typing import Iterator

from src.harness.guardrails import mask_pii

_langfuse = None
if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
    from langfuse import Langfuse, propagate_attributes

    _langfuse = Langfuse(mask=lambda data, **_: mask_pii(data))


@contextlib.contextmanager
def trace_turn(conversation_id: str, domain: str, user_text: str) -> Iterator[None]:
    """Agrupa todo lo que pasa en un turno bajo la sesión (= conversación) en Langfuse."""
    if _langfuse is None:
        yield
        return
    with propagate_attributes(session_id=conversation_id, tags=[domain], trace_name=f"turno-{domain}"):
        with _langfuse.start_as_current_observation(name="turno", as_type="agent", input=user_text):
            yield


def log_generation(model: str, messages: list[dict], output: str, tool_calls: list, usage: dict, cost: float) -> None:
    if _langfuse is None:
        return
    with _langfuse.start_as_current_observation(name="llm", as_type="generation", model=model,
                                                input=messages[-6:], usage_details=usage,
                                                cost_details={"total": cost}) as gen:
        gen.update(output={"text": output, "tool_calls": tool_calls})


def log_tool(name: str, args: dict, result: str) -> None:
    if _langfuse is None:
        return
    with _langfuse.start_as_current_observation(name=name, as_type="tool", input=args) as span:
        span.update(output=result)


def flush() -> None:
    if _langfuse is not None:
        _langfuse.flush()


class Metrics:
    """Ventana de los últimos 1000 turnos. Se consulta en GET /metrics."""

    def __init__(self, size: int = 1000):
        self.ttft_ms: deque[float] = deque(maxlen=size)
        self.turn_ms: deque[float] = deque(maxlen=size)
        self.cost_by_conversation: dict[str, float] = {}
        self.counters: Counter[str] = Counter()

    @staticmethod
    def _pct(values: deque[float], p: float) -> float | None:
        if not values:
            return None
        if len(values) == 1:
            return round(values[0], 1)
        return round(statistics.quantiles(values, n=100, method="inclusive")[int(p) - 1], 1)

    def snapshot(self) -> dict:
        costs = list(self.cost_by_conversation.values())
        return {
            "turnos": len(self.turn_ms),
            "conversaciones": len(costs),
            "ttft_ms": {"p50": self._pct(self.ttft_ms, 50), "p95": self._pct(self.ttft_ms, 95)},
            "turno_ms": {"p50": self._pct(self.turn_ms, 50), "p95": self._pct(self.turn_ms, 95)},
            "costo_usd_promedio_conversacion": round(statistics.mean(costs), 5) if costs else None,
            "costo_usd_estimado_1000_conversaciones": round(statistics.mean(costs) * 1000, 2) if costs else None,
            "eventos": dict(self.counters),
        }


metrics = Metrics()
