"""Clientes de LLM con una interfaz común: `stream(messages, tools)` → deltas de texto + resultado final.

Formato interno de mensajes = formato Chat Completions de OpenAI (es el que manda ElevenLabs).
El proveedor de Anthropic traduce ida y vuelta. Así el loop del agente no sabe qué modelo responde,
y el fallback entre proveedores (harness) es trivial.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol

import anthropic
import openai

# Claves privadas que agregamos a los mensajes y que no viajan a otros proveedores.
ANTHROPIC_RAW = "_anthropic_content"


@dataclass
class TextDelta:
    text: str


@dataclass
class LLMResult:
    provider: str
    model: str
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)  # formato OpenAI
    input_tokens: int = 0
    output_tokens: int = 0
    raw_assistant: list | None = None  # bloques nativos de Anthropic (incluye thinking) para el loop de tools

    def assistant_message(self) -> dict:
        msg: dict = {"role": "assistant", "content": self.text or None}
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        if self.raw_assistant is not None:
            msg[ANTHROPIC_RAW] = self.raw_assistant
        return msg


class LLMError(Exception):
    """Falla del proveedor (red, 5xx, 429, timeout, refusal). El router decide si hace fallback."""


class Provider(Protocol):
    name: str
    model: str

    def stream(self, messages: list[dict], tools: list[dict]) -> AsyncIterator[TextDelta | LLMResult]: ...


def _public(msg: dict) -> dict:
    return {k: v for k, v in msg.items() if not k.startswith("_")}


# ─────────────────────────────── OpenAI ───────────────────────────────


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str, max_tokens: int = 400):
        self.model = model
        self.max_tokens = max_tokens
        self._client: openai.AsyncOpenAI | None = None

    @property
    def client(self) -> openai.AsyncOpenAI:  # se crea al primer uso: la app arranca aunque falte una key
        if self._client is None:
            self._client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"), max_retries=0)
        return self._client

    async def stream(self, messages: list[dict], tools: list[dict]) -> AsyncIterator[TextDelta | LLMResult]:
        result = LLMResult(provider=self.name, model=self.model)
        calls: dict[int, dict] = {}
        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=[_public(m) for m in messages],
                tools=tools or openai.NOT_GIVEN,
                max_tokens=self.max_tokens,
                temperature=0.3,
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                if chunk.usage:
                    result.input_tokens = chunk.usage.prompt_tokens
                    result.output_tokens = chunk.usage.completion_tokens
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    result.text += delta.content
                    yield TextDelta(delta.content)
                for tc in delta.tool_calls or []:
                    call = calls.setdefault(tc.index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                    call["id"] = tc.id or call["id"]
                    if tc.function and tc.function.name:
                        call["function"]["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        call["function"]["arguments"] += tc.function.arguments
        except openai.OpenAIError as e:
            raise LLMError(f"openai:{self.model}: {e}") from e
        result.tool_calls = [calls[i] for i in sorted(calls)]
        yield result


# ─────────────────────────────── Anthropic ───────────────────────────────


def to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    """Chat Completions → Messages API (system aparte, tool_calls → tool_use, tool → tool_result)."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system" and m.get("content"))
    out: list[dict] = []

    def push(role: str, blocks: list[dict]) -> None:
        if out and out[-1]["role"] == role:  # la API espera roles alternados: se fusionan consecutivos
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": blocks})

    for m in messages:
        if m["role"] == "user":
            push("user", [{"type": "text", "text": m["content"]}])
        elif m["role"] == "assistant":
            if m.get(ANTHROPIC_RAW):  # generado por Claude: se devuelve tal cual (thinking incluido)
                push("assistant", list(m[ANTHROPIC_RAW]))
                continue
            blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            for tc in m.get("tool_calls") or []:
                blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"],
                               "input": json.loads(tc["function"]["arguments"] or "{}")})
            if blocks:
                push("assistant", blocks)
        elif m["role"] == "tool":
            push("user", [{"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}])
    if out and out[0]["role"] == "assistant":  # el primer mensaje de ElevenLabs es del agente
        out.insert(0, {"role": "user", "content": [{"type": "text", "text": "(se inicia la llamada)"}]})
    return system, out


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str, max_tokens: int = 2048):
        self.model = model
        self.max_tokens = max_tokens  # incluye el razonamiento interno del modelo, no solo la respuesta
        self._client: anthropic.AsyncAnthropic | None = None

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=0)
        return self._client

    async def stream(self, messages: list[dict], tools: list[dict]) -> AsyncIterator[TextDelta | LLMResult]:
        """TODO [C18]: proveedor de respaldo para el fallback. Usá to_anthropic(messages) para traducir el
        formato, client.messages.stream(...) para el texto y get_final_message() para tool_use y usage.
        Convertí los errores del SDK en LLMError para que el router pueda hacer fallback."""
        raise NotImplementedError
        yield  # noqa


def build_provider(spec: str) -> Provider:
    """'openai:gpt-4.1-mini' → OpenAIProvider('gpt-4.1-mini')."""
    provider, _, model = spec.partition(":")
    if provider == "openai":
        return OpenAIProvider(model)
    if provider == "anthropic":
        return AnthropicProvider(model)
    raise ValueError(f"Proveedor desconocido en '{spec}'")
