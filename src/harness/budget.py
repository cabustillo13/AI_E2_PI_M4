"""Presupuesto de costo por conversación.

- Gasto < 70 % del presupuesto → modelo normal.
- Gasto >= 70 % → se degrada al modelo barato (LLM_CHEAP).
- Gasto >= 100 % → el agente cierra la llamada con un mensaje fijo, sin llamar a ningún LLM.

En memoria: alcanza con una sola réplica. Con varias réplicas iría a Redis (mismo contrato).
"""

from __future__ import annotations

from collections import defaultdict
from enum import Enum


class BudgetState(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    EXHAUSTED = "exhausted"


class BudgetTracker:
    def __init__(self, budget_usd: float, degrade_ratio: float = 0.7):
        self.budget_usd = budget_usd
        self.degrade_ratio = degrade_ratio
        self._spent: dict[str, float] = defaultdict(float)

    def add(self, conversation_id: str, usd: float) -> None:
        self._spent[conversation_id] += usd

    def spent(self, conversation_id: str) -> float:
        return self._spent.get(conversation_id, 0.0)

    def state(self, conversation_id: str) -> BudgetState:
        spent = self.spent(conversation_id)
        if spent >= self.budget_usd:
            return BudgetState.EXHAUSTED
        if spent >= self.budget_usd * self.degrade_ratio:
            return BudgetState.DEGRADED
        return BudgetState.OK
