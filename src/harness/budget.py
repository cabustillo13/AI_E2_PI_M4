"""Presupuesto de costo por conversación (SCAFFOLD) [C18].

El presupuesto en USD está en el frontmatter del domain pack (`presupuesto_usd_conversacion`).
Definí qué hace el agente al acercarse (¿modelo más barato?) y al superarlo (¿cierre cordial?).
"""

from __future__ import annotations


class BudgetTracker:
    def __init__(self, budget_usd: float, degrade_ratio: float = 0.7):
        self.budget_usd = budget_usd
        self.degrade_ratio = degrade_ratio

    def add(self, conversation_id: str, usd: float) -> None:
        raise NotImplementedError

    def state(self, conversation_id: str) -> str:
        """TODO: devolver 'ok' | 'degraded' | 'exhausted'."""
        raise NotImplementedError
