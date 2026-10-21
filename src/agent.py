"""Loop del agente (un turno de conversación).

    mensajes de ElevenLabs → [guardrails] → LLM (router con fallback) ⇄ tools MCP → texto en streaming

Es el mismo loop ReAct de M3 (clase 11), con el harness de M4 alrededor:
presupuesto, fallback, tope de iteraciones, guardrails y trazas.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

from src.domain import Domain
from src.harness.budget import BudgetState, BudgetTracker
from src.harness.guardrails import sanitize_user_text
from src.harness.router import LLMRouter
from src.llm.pricing import cost_usd
from src.llm.providers import LLMError, LLMResult, TextDelta
from src.mcp_client import MCPToolbox
from src.memory import ConversationStore, merge_history
from src.observability import log_generation, log_tool, metrics, trace_turn

log = logging.getLogger(__name__)

MSG_BUDGET = "Para seguir con tu gestión te voy a derivar con una persona del equipo. Gracias por comunicarte."
MSG_TOO_MANY_STEPS = "Perdón, no estoy pudiendo resolverlo. Te sugiero comunicarte con una persona del equipo."
MSG_ALL_FAILED = "Disculpá, estoy con un problema técnico. Por favor volvé a llamar en unos minutos."


@dataclass
class ToolCallsOut:
    """Tool de la plataforma (end_call, transfer...) que debe ejecutar ElevenLabs, no el backend."""
    tool_calls: list[dict]


@dataclass
class TurnSummary:
    conversation_id: str
    models: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    cost_usd: float = 0.0
    ttft_ms: float | None = None
    guardrail_hits: int = 0
    budget_state: str = BudgetState.OK.value


@dataclass
class TurnContext:
    conversation_id: str
    channel_context: str = ""                                    # system prompt que manda ElevenLabs
    platform_tools: list[dict] = field(default_factory=list)     # tools de sistema de ElevenLabs


class Agent:
    def __init__(self, domain: Domain, toolbox: MCPToolbox, router: LLMRouter, budget: BudgetTracker,
                 memory: ConversationStore, max_tool_iterations: int = 5):
        self.domain = domain
        self.toolbox = toolbox
        self.router = router
        self.budget = budget
        self.memory = memory
        self.max_tool_iterations = max_tool_iterations

    def _system(self, ctx: TurnContext) -> dict:
        prompt = self.domain.system_prompt()
        if ctx.channel_context:
            prompt += f"\n\n# Contexto de la llamada\n\n{ctx.channel_context}"
        return {"role": "system", "content": prompt}

    def _sanitize(self, history: list[dict], summary: TurnSummary) -> None:
        for m in history:
            if m["role"] == "user" and isinstance(m.get("content"), str):
                m["content"], hit = sanitize_user_text(m["content"])
                summary.guardrail_hits += int(hit)

    async def run(self, incoming: list[dict], ctx: TurnContext) -> AsyncIterator[TextDelta | ToolCallsOut | TurnSummary]:
        cid = ctx.conversation_id
        start = time.perf_counter()
        summary = TurnSummary(conversation_id=cid)
        history = merge_history(self.memory.get(cid), incoming)
        self._sanitize(history, summary)
        last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")

        spoken = {"text": "", "new_call": False}

        def speak(text: str) -> TextDelta:
            if summary.ttft_ms is None:
                summary.ttft_ms = (time.perf_counter() - start) * 1000
            prev = spoken["text"]
            if spoken["new_call"] and prev and not prev[-1].isspace() and text and not text[0].isspace():
                text = " " + text  # 2.ª llamada al LLM en el mismo turno: que no queden frases pegadas
            spoken.update(text=prev + text, new_call=False)
            return TextDelta(text)

        with trace_turn(cid, self.domain.id, last_user):
            if self.budget.state(cid) == BudgetState.EXHAUSTED:
                # Presupuesto agotado: mensaje fijo, sin gastar un token más.
                metrics.counters["presupuesto_agotado"] += 1
                summary.budget_state = BudgetState.EXHAUSTED.value
                yield speak(MSG_BUDGET)
                history.append({"role": "assistant", "content": MSG_BUDGET})
                end_call = [t for t in ctx.platform_tools if t["function"]["name"] == "end_call"]
                if end_call:
                    yield ToolCallsOut([{"id": f"call_budget_{len(history)}", "type": "function",
                                         "function": {"name": "end_call", "arguments": "{}"}}])
            else:
                tools = self.toolbox.openai_tools + ctx.platform_tools
                for _ in range(self.max_tool_iterations):
                    degrade = self.budget.state(cid) == BudgetState.DEGRADED
                    summary.budget_state = self.budget.state(cid).value
                    result: LLMResult | None = None
                    spoken["new_call"] = True
                    try:
                        async for event in self.router.stream([self._system(ctx), *history], tools, degrade):
                            if isinstance(event, TextDelta):
                                yield speak(event.text)
                            else:
                                result = event
                    except LLMError as e:
                        log.error("Sin modelos disponibles: %s", e)
                        metrics.counters["todos_los_modelos_fallaron"] += 1
                        yield speak(MSG_ALL_FAILED)
                        history.append({"role": "assistant", "content": MSG_ALL_FAILED})
                        break

                    cost = cost_usd(result.model, result.input_tokens, result.output_tokens)
                    self.budget.add(cid, cost)
                    summary.cost_usd += cost
                    summary.models.append(f"{result.provider}:{result.model}")
                    log_generation(result.model, history, result.text, result.tool_calls,
                                   {"input": result.input_tokens, "output": result.output_tokens}, cost)
                    history.append(result.assistant_message())
                    if not result.tool_calls:
                        break

                    platform_calls = []
                    for tc in result.tool_calls:
                        name = tc["function"]["name"]
                        if name not in self.toolbox.names:
                            platform_calls.append(tc)
                            continue
                        try:
                            args = json.loads(tc["function"]["arguments"] or "{}")
                            output = await self.toolbox.call(name, args)
                        except json.JSONDecodeError:
                            args, output = {}, json.dumps({"ok": False, "error": "Argumentos no son JSON válido"})
                        except Exception:  # en voz no se puede cortar el stream: el LLM explica el error
                            log.exception("Falla ejecutando la tool %s", name)
                            metrics.counters["error_de_tool"] += 1
                            output = json.dumps({"ok": False, "error": "El sistema no respondió, probá de nuevo"})
                        log_tool(name, args, output)
                        summary.tool_calls.append({"name": name, "arguments": args, "result": output})
                        history.append({"role": "tool", "tool_call_id": tc["id"], "content": output})
                    if platform_calls:
                        yield ToolCallsOut(platform_calls)
                        break
                else:
                    # Stopping rule: demasiadas vueltas de tools sin respuesta final.
                    metrics.counters["tope_de_iteraciones"] += 1
                    yield speak(MSG_TOO_MANY_STEPS)
                    history.append({"role": "assistant", "content": MSG_TOO_MANY_STEPS})

        self.memory.save(cid, history)
        metrics.turn_ms.append((time.perf_counter() - start) * 1000)
        if summary.ttft_ms is not None:
            metrics.ttft_ms.append(summary.ttft_ms)
        metrics.cost_by_conversation[cid] = self.budget.spent(cid)
        metrics.counters["guardrail_dato_sensible"] += summary.guardrail_hits
        if summary.budget_state == BudgetState.DEGRADED.value:
            metrics.counters["turnos_con_modelo_barato"] += 1
        yield summary
