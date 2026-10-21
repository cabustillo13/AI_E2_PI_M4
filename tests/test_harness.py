"""Harness: fallback entre modelos, presupuesto, rate limit y guardrails."""

import asyncio

from src.harness.budget import BudgetState, BudgetTracker
from src.harness.guardrails import SENSITIVE_PLACEHOLDER, mask_pii, sanitize_user_text
from src.harness.rate_limit import RateLimiter
from src.harness.router import MID_STREAM_APOLOGY, LLMRouter
from src.llm.providers import LLMError, LLMResult, TextDelta
from tests.fakes import FakeProvider


async def collect(router, degrade=False):
    events = [e async for e in router.stream([{"role": "user", "content": "hola"}], [], degrade)]
    text = "".join(e.text for e in events if isinstance(e, TextDelta))
    return text, next(e for e in events if isinstance(e, LLMResult))


def test_fallback_si_falla_el_primario():
    fallos = []
    router = LLMRouter([FakeProvider([LLMError("503")], model="primario"), FakeProvider(["hola desde respaldo"],
                       model="respaldo")], cheap=FakeProvider([]), first_token_timeout_s=1,
                       on_fallback=lambda frm, err: fallos.append(frm))
    text, result = asyncio.run(collect(router))
    assert result.model == "respaldo" and "respaldo" in text and fallos == ["fake:primario"]


def test_fallback_por_timeout_del_primer_token():
    router = LLMRouter([FakeProvider([("lento", 2)], model="lento"), FakeProvider(["rápido"], model="rapido")],
                       cheap=FakeProvider([]), first_token_timeout_s=0.2)
    _, result = asyncio.run(collect(router))
    assert result.model == "rapido"


def test_si_ya_hablo_no_hace_fallback_y_se_disculpa():
    respaldo = FakeProvider(["no debería usarse"], model="respaldo")
    router = LLMRouter([FakeProvider([("corta", "Te cuento que")], model="primario"), respaldo],
                       cheap=FakeProvider([]), first_token_timeout_s=1)
    text, _ = asyncio.run(collect(router))
    assert text.startswith("Te cuento que") and MID_STREAM_APOLOGY in text and respaldo.calls == []


def test_degradado_usa_modelo_barato():
    router = LLMRouter([FakeProvider(["caro"], model="caro")], cheap=FakeProvider(["barato"], model="barato"),
                       first_token_timeout_s=1)
    _, result = asyncio.run(collect(router, degrade=True))
    assert result.model == "barato"


def test_presupuesto_por_conversacion():
    budget = BudgetTracker(budget_usd=0.01, degrade_ratio=0.7)
    assert budget.state("c1") == BudgetState.OK
    budget.add("c1", 0.008)
    assert budget.state("c1") == BudgetState.DEGRADED
    budget.add("c1", 0.003)
    assert budget.state("c1") == BudgetState.EXHAUSTED
    assert budget.state("c2") == BudgetState.OK  # aislado por conversación


def test_rate_limit():
    limiter = RateLimiter(max_per_minute=2)
    assert limiter.allow("a") and limiter.allow("a") and not limiter.allow("a")
    assert limiter.allow("b")


def test_guardrail_tarjeta_y_cbu():
    texto, hit = sanitize_user_text("mi tarjeta es 4509 9535 6623 3704 y el cvv 123")
    assert hit and "4509" not in texto and "123" not in texto and SENSITIVE_PLACEHOLDER in texto
    texto, hit = sanitize_user_text("el CBU es 0110599520000001234567")
    assert hit and SENSITIVE_PLACEHOLDER in texto


def test_guardrail_no_toca_dni_ni_montos():
    texto, hit = sanitize_user_text("mi DNI es 30111222 y puedo pagar 15000")
    assert not hit and "30111222" in texto


def test_mascara_pii_para_trazas():
    assert mask_pii({"msg": "DNI 30.111.222, tel +5491155550001"}) == {"msg": "DNI [DNI], tel [TEL]"}
