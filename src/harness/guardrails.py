"""Guardrails propios (SCAFFOLD) [C18] (además de los de la plataforma ElevenLabs).

Regla del módulo: el LLM nunca toca datos de pago. Que lo diga el prompt no alcanza.
"""

from __future__ import annotations


def sanitize_user_text(text: str) -> tuple[str, bool]:
    """TODO [C18]: reemplazar números de tarjeta (13–19 dígitos que pasan Luhn), CBU (22 dígitos) y códigos de
    seguridad por un placeholder ANTES de mandar el texto al LLM. Devuelve (texto limpio, si hubo cambios).
    Ojo: el STT suele transcribir la tarjeta con espacios ("4509 9535 ...")."""
    raise NotImplementedError


def mask_pii(data):
    """TODO [C18]: enmascarar DNI, teléfonos y tarjetas en lo que se envía a Langfuse (Langfuse(mask=...))."""
    return data
