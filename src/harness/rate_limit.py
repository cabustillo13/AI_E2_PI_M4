"""Rate limit de ventana deslizante: N requests por minuto por cliente (conversación o IP).

Protege el presupuesto ante loops (p. ej. un cliente que reintenta sin parar) y abuso.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_per_minute: int, window_s: float = 60.0):
        self.max = max_per_minute
        self.window = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.max:
            return False
        hits.append(now)
        return True
