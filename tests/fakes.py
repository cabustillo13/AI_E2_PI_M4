"""LLM falso y guionado: permite testear el loop, el harness y la API sin gastar tokens."""

from __future__ import annotations

import asyncio
import json

from src.llm.providers import LLMError, LLMResult, TextDelta


def tool_call(name: str, **arguments) -> dict:
    return {"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


class FakeProvider:
    """Cada llamada a stream() consume el siguiente paso del guion.
    Un paso es: str (texto) | list[dict] (tool calls) | Exception | ("lento", segundos)."""

    def __init__(self, script: list, name: str = "fake", model: str = "gpt-4.1-mini"):
        self.script = list(script)
        self.name, self.model = name, model
        self.calls: list[list[dict]] = []

    async def stream(self, messages, tools):
        self.calls.append(messages)
        step = self.script.pop(0) if self.script else "ok"
        if isinstance(step, Exception):
            raise step
        if isinstance(step, tuple) and step[0] == "lento":
            await asyncio.sleep(step[1])
            step = "tarde"
        if isinstance(step, tuple) and step[0] == "corta":  # habla y después falla
            yield TextDelta(step[1])
            raise LLMError("se cortó el stream")
        if isinstance(step, list):
            yield LLMResult(provider=self.name, model=self.model, tool_calls=step, input_tokens=1000, output_tokens=50)
            return
        for word in step.split(" "):
            yield TextDelta(word + " ")
        yield LLMResult(provider=self.name, model=self.model, text=step, input_tokens=1000, output_tokens=50)
