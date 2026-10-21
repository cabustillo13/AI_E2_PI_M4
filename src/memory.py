"""Memoria de corto plazo por conversación.

ElevenLabs solo recuerda lo que se *habló*. Las llamadas a tools que hace el backend (y sus
resultados: slot_id, turno_id...) no vuelven en el historial del siguiente turno. Por eso el backend
guarda su propia versión completa de la conversación y solo toma de ElevenLabs los mensajes nuevos.
"""

from __future__ import annotations

import time

TTL_S = 2 * 60 * 60


class ConversationStore:
    def __init__(self) -> None:
        self._items: dict[str, tuple[float, list[dict]]] = {}

    def get(self, conversation_id: str) -> list[dict]:
        self._evict()
        return list(self._items.get(conversation_id, (0, []))[1])

    def save(self, conversation_id: str, messages: list[dict]) -> None:
        self._items[conversation_id] = (time.monotonic(), messages)

    def _evict(self) -> None:
        now = time.monotonic()
        for key in [k for k, (ts, _) in self._items.items() if now - ts > TTL_S]:
            del self._items[key]


def merge_history(stored: list[dict], incoming: list[dict]) -> list[dict]:
    """Historial guardado + mensajes de ElevenLabs posteriores a su última respuesta del asistente."""
    incoming = [m for m in incoming if m["role"] != "system"]
    if not stored:
        return incoming
    last_assistant = max((i for i, m in enumerate(incoming) if m["role"] == "assistant"), default=-1)
    return stored + incoming[last_assistant + 1:]
