"""Rate limit (SCAFFOLD) [C18]. N requests por minuto por cliente (conversación o IP) → HTTP 429."""

from __future__ import annotations


class RateLimiter:
    def __init__(self, max_per_minute: int):
        self.max = max_per_minute

    def allow(self, key: str) -> bool:
        """TODO [C18]: ventana deslizante (collections.deque de timestamps por key)."""
        raise NotImplementedError
