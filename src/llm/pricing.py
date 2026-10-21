"""Precio por 1M de tokens (USD, input / output). Fuente: páginas de pricing de cada proveedor, oct-2026.

Revisalo antes de cada cohorte: si un modelo no está acá, el costo se registra como 0 y el
presupuesto por conversación deja de proteger (por eso se loguea un warning).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o-mini": (0.15, 0.60),
    # Anthropic
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in PRICES_PER_MTOK:
        log.warning("Modelo sin precio en pricing.py: %s (costo registrado = 0)", model)
        return 0.0
    price_in, price_out = PRICES_PER_MTOK[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000
