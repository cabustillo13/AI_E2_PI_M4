"""Loop del agente frente a lo que pasa en voz: interrupciones y pedidos simultáneos de una conversación."""

import asyncio

from src.agent import TurnContext
from tests.fakes import make_agent, tool_call

TURNO = {"ok": True, "turno_id": "T-1002", "cuando": "lunes 26 de octubre a las 10:00"}


def test_turno_interrumpido_guarda_lo_que_hicieron_las_tools():
    """ElevenLabs corta el turno después de que una tool reservó: el turno siguiente tiene que saberlo."""
    agent, _ = make_agent([[tool_call("agendar_turno", dni="30111222", slot_id="S1")], ("lento", 5)],
                          tools={"agendar_turno": TURNO})

    async def cortar():
        gen = agent.run([{"role": "user", "content": "agendame el de las diez"}], TurnContext("conv-corte"))
        task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0.5)  # la tool ya corrió; el LLM está generando la respuesta
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await gen.aclose()

    asyncio.run(cortar())
    historia = agent.memory.get("conv-corte")
    assert any(m["role"] == "tool" and "T-1002" in m["content"] for m in historia)


def test_tool_cortada_a_mitad_queda_cerrada_en_el_historial():
    """Si el corte llega antes del resultado, la llamada queda con un resultado de 'interrumpida'."""
    agent, _ = make_agent([[tool_call("agendar_turno", dni="30111222", slot_id="S1")]], tools={"agendar_turno": TURNO})

    async def tool_lenta(name, args):
        await asyncio.sleep(5)

    agent.toolbox.call = tool_lenta

    async def cortar():
        gen = agent.run([{"role": "user", "content": "agendame"}], TurnContext("conv-mitad"))
        task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0.5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await gen.aclose()

    asyncio.run(cortar())
    historia = agent.memory.get("conv-mitad")
    llamadas = [tc["id"] for m in historia if m["role"] == "assistant" for tc in m.get("tool_calls") or []]
    respuestas = {m["tool_call_id"]: m["content"] for m in historia if m["role"] == "tool"}
    assert llamadas and all(c in respuestas for c in llamadas)
    assert "interrumpió" in respuestas[llamadas[0]]


def test_pedidos_simultaneos_de_la_misma_conversacion_se_serializan():
    agent, _ = make_agent([("lento", 0.3), ("lento", 0.3)])
    eventos = []

    async def turno(n):
        async for ev in agent.run([{"role": "user", "content": f"hola {n}"}], TurnContext("conv-paralela")):
            eventos.append((n, type(ev).__name__))

    async def ambos():
        await asyncio.gather(turno(1), turno(2))

    asyncio.run(ambos())
    primero = eventos[0][0]
    fin = eventos.index((primero, "TurnSummary"))
    assert all(n == primero for n, _ in eventos[:fin + 1])  # el otro turno arranca recién cuando termina este
