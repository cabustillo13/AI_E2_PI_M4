"""Fallback entre modelos.

Recorre la cadena LLM_CHAIN en orden. Pasa al siguiente modelo si el actual falla o tarda más de
FIRST_TOKEN_TIMEOUT_S en dar la primera señal, **siempre que todavía no se haya hablado nada**:
si el modelo ya empezó a responder por voz, no se puede "desdecir", así que se corta con una disculpa.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Callable

from src.llm.providers import LLMError, LLMResult, Provider, TextDelta

log = logging.getLogger(__name__)

MID_STREAM_APOLOGY = " Perdón, tuve un problema técnico. ¿Me repetís lo último?"


class LLMRouter:
    def __init__(self, chain: list[Provider], cheap: Provider, first_token_timeout_s: float,
                 on_fallback: Callable[[str, str], None] = lambda frm, err: None):
        self.chain = chain
        self.cheap = cheap
        self.timeout = first_token_timeout_s
        self.on_fallback = on_fallback

    async def stream(self, messages: list[dict], tools: list[dict], degrade: bool = False
                     ) -> AsyncIterator[TextDelta | LLMResult]:
        # Presupuesto casi agotado → se empieza por el modelo barato, el resto queda de respaldo.
        chain = [self.cheap, *self.chain] if degrade else self.chain
        last_error: Exception | None = None
        for provider in chain:
            spoke = False
            it = provider.stream(messages, tools).__aiter__()
            try:
                first = await asyncio.wait_for(it.__anext__(), timeout=self.timeout)
                if isinstance(first, TextDelta):
                    spoke = True
                yield first
                async for event in it:
                    if isinstance(event, TextDelta):
                        spoke = True
                    yield event
                return
            except (LLMError, asyncio.TimeoutError) as e:
                last_error = e
                reason = "timeout primer token" if isinstance(e, asyncio.TimeoutError) else str(e)
                log.warning("Falla %s:%s (%s)", provider.name, provider.model, reason)
                if spoke:
                    yield TextDelta(MID_STREAM_APOLOGY)
                    yield LLMResult(provider=provider.name, model=provider.model, text=MID_STREAM_APOLOGY)
                    return
                self.on_fallback(f"{provider.name}:{provider.model}", reason)
            finally:
                await it.aclose()
        raise LLMError(f"Todos los modelos fallaron. Último error: {last_error}")
