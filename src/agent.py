"""Loop del agente (SCAFFOLD): un turno de conversación.

    mensajes de ElevenLabs → [guardrails] → LLM (router con fallback) ⇄ tools MCP → texto en streaming

Es el loop ReAct de M3 (clase 11) con el harness de M4 alrededor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator

from src.domain import Domain
from src.harness.budget import BudgetTracker
from src.harness.router import LLMRouter
from src.llm.providers import TextDelta
from src.mcp_client import MCPToolbox
from src.memory import ConversationStore


@dataclass
class TurnContext:
    conversation_id: str
    channel_context: str = ""                                 # system prompt que manda ElevenLabs
    platform_tools: list[dict] = field(default_factory=list)  # tools de sistema de ElevenLabs (end_call...)


class Agent:
    def __init__(self, domain: Domain, toolbox: MCPToolbox, router: LLMRouter, budget: BudgetTracker,
                 memory: ConversationStore, max_tool_iterations: int = 5):
        self.domain = domain
        self.toolbox = toolbox
        self.router = router                            # LLMs con fallback (src/harness/router.py)
        self.budget = budget                            # costo por conversación (src/harness/budget.py)
        self.memory = memory                            # historial completo por conversación (src/memory.py)
        self.max_tool_iterations = max_tool_iterations  # stopping rule del loop de tools

    async def run(self, incoming: list[dict], ctx: TurnContext) -> AsyncIterator[TextDelta]:
        """TODO [C16 + C18]

        1. history = merge_history(self.memory.get(cid), incoming)   (src/memory.py: ya está hecho)
        2. Guardrail de entrada: sacar números de tarjeta / CBU de los mensajes del usuario.
        3. Si el presupuesto de la conversación está agotado → mensaje fijo de cierre, sin llamar al LLM.
        4. Loop (máximo self.max_tool_iterations vueltas = stopping rule):
             - llamar a self.router.stream([system = self.domain.system_prompt(), *history],
               tools = self.toolbox.openai_tools + ctx.platform_tools, degrade = presupuesto "degraded")
             - ir emitiendo (yield) los TextDelta a medida que llegan → se hablan en la llamada
             - sumar el costo con self.budget.add(cid, cost_usd(...))   (src/llm/pricing.py)
             - si no hay tool_calls → fin del turno
             - si hay tool_calls del MCP → ejecutar con self.toolbox.call(name, args) y agregar los
               mensajes {"role": "tool", ...} al historial; volver a llamar al LLM
        5. self.memory.save(cid, history) y registrar métricas / trazas (src/observability.py).

        Ojo con la voz: si la persona habla de corrido o interrumpe, ElevenLabs corta el turno en curso y
        manda uno nuevo. Pensá qué pasa si la tool ya reservó un turno cuando se corta (¿se guarda la
        memoria?) y si dos pedidos de la misma conversación pueden correr a la vez (asyncio.Lock).
        Las tools del MCP ya son idempotentes: repetir una reserva devuelve `ya_estaba_agendado`.
        """
        raise NotImplementedError
        yield  # noqa: (hace que la función sea un async generator)
