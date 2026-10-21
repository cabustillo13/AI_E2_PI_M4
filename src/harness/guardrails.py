"""Guardrails propios (además de los de la plataforma ElevenLabs).

1. Entrada: si la persona dicta un número de tarjeta o un CBU, se elimina ANTES de llegar al LLM.
   Así se cumple "el LLM nunca toca datos de pago" aunque el prompt falle.
2. Entrada: se recorta el mensaje a un largo máximo (mitiga inyecciones largas y costo).
3. Observabilidad: se enmascaran DNI, teléfonos y tarjetas en lo que se envía a Langfuse.
"""

from __future__ import annotations

import re

SENSITIVE_PLACEHOLDER = "[DATO SENSIBLE ELIMINADO]"
MAX_USER_CHARS = 1000

# Secuencias de 13 a 22 dígitos, permitiendo espacios o guiones (así llega del STT: "4509 9535 ...").
_LONG_DIGITS = re.compile(r"\b\d(?:[ -]?\d){12,21}\b")
_CVV = re.compile(r"\b(cvv|cvc|c[oó]digo de seguridad)\D{0,20}\d{3,4}\b", re.IGNORECASE)
_DNI = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}\b")
_PHONE = re.compile(r"\+?\d{10,13}\b")


def luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _redact_number(match: re.Match) -> str:
    digits = re.sub(r"\D", "", match.group())
    is_card = 13 <= len(digits) <= 19 and luhn_ok(digits)
    is_cbu = len(digits) == 22
    return SENSITIVE_PLACEHOLDER if is_card or is_cbu else match.group()


def sanitize_user_text(text: str) -> tuple[str, bool]:
    """Devuelve (texto limpio, si se eliminó algo sensible)."""
    clean = _LONG_DIGITS.sub(_redact_number, text)
    clean = _CVV.sub(SENSITIVE_PLACEHOLDER, clean)
    return clean[:MAX_USER_CHARS], clean != text


def mask_pii(data):
    """Función de máscara para Langfuse: se aplica a todo input/output que se traza."""
    if isinstance(data, str):
        data = _PHONE.sub("[TEL]", data)
        data = _LONG_DIGITS.sub("[NUM]", data)
        return _DNI.sub("[DNI]", data)
    if isinstance(data, dict):
        return {k: mask_pii(v) for k, v in data.items()}
    if isinstance(data, list):
        return [mask_pii(v) for v in data]
    return data
