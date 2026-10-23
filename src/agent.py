"""Loop del agente (un turno de conversación) — SCAFFOLD.

    mensajes de ElevenLabs → [guardrails] → LLM (router con fallback) ⇄ tools MCP → texto en streaming

Es el loop ReAct de M3 (clase 11) con el harness de M4 alrededor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator

from src.domain import Domain
from src.llm.providers import TextDelta
from src.mcp_client import MCPToolbox
from src.memory import ConversationStore


@dataclass
class TurnContext:
    conversation_id: str
    channel_context: str = ""                                 # system prompt que manda ElevenLabs
    platform_tools: list[dict] = field(default_factory=list)  # tools de sistema de ElevenLabs (end_call...)


class Agent:
    def __init__(self, domain: Domain, toolbox: MCPToolbox, memory: ConversationStore, **harness):
        self.domain = domain
        self.toolbox = toolbox
        self.memory = memory
        self.harness = harness  # router, budget, max_tool_iterations... (lo definís vos)

    async def run(self, incoming: list[dict], ctx: TurnContext) -> AsyncIterator[TextDelta]:
        """TODO [C16 + C18]

        1. history = merge_history(self.memory.get(cid), incoming)   (src/memory.py: ya está hecho)
        2. Guardrail de entrada: sacar números de tarjeta / CBU de los mensajes del usuario.
        3. Si el presupuesto de la conversación está agotado → mensaje fijo de cierre, sin llamar al LLM.
        4. Loop (máximo N vueltas = stopping rule):
             - llamar al LLM con [system = self.domain.system_prompt(), *history] y
               tools = self.toolbox.openai_tools + ctx.platform_tools
             - ir emitiendo (yield) los TextDelta a medida que llegan → se hablan en la llamada
             - sumar el costo al presupuesto (src/llm/pricing.py)
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
