"""Fallback entre modelos — SCAFFOLD [C18].

Recorrer una cadena de proveedores (settings.llm_chain) y pasar al siguiente si el actual falla
(LLMError) o tarda más de settings.first_token_timeout_s en dar la primera señal.

Pregunta de diseño para resolver (y defender): ¿qué hacés si el modelo ya empezó a hablar y se cae?
"""

from __future__ import annotations

from typing import AsyncIterator

from src.llm.providers import LLMResult, Provider, TextDelta


class LLMRouter:
    def __init__(self, chain: list[Provider], cheap: Provider, first_token_timeout_s: float):
        self.chain = chain
        self.cheap = cheap
        self.timeout = first_token_timeout_s

    async def stream(self, messages: list[dict], tools: list[dict], degrade: bool = False
                     ) -> AsyncIterator[TextDelta | LLMResult]:
        """TODO: si degrade=True empezar por el modelo barato. Tip: asyncio.wait_for sobre el primer evento."""
        raise NotImplementedError
        yield  # noqa
