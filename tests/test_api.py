"""API end-to-end con MCP real (subproceso) y LLM falso: auth, SSE, loop de tools, memoria y presupuesto."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.fakes import FakeProvider, tool_call

AUTH = {"Authorization": "Bearer test-key"}


@pytest.fixture
def make_client(monkeypatch):
    def _make(script: list, domain: str = "clinica", cheap_script: list | None = None):
        import src.main as main

        monkeypatch.setattr(main.settings, "domain", domain)
        monkeypatch.setattr(main.settings, "api_key", "test-key")
        monkeypatch.setattr(main.settings, "llm_chain", ("openai:gpt-4.1-mini",))
        primary = FakeProvider(script, model="gpt-4.1-mini")
        cheap = FakeProvider(cheap_script or ["respuesta barata"], model="gpt-4.1-nano")
        providers = iter([primary, cheap])
        monkeypatch.setattr(main, "build_provider", lambda spec: next(providers, primary))
        return TestClient(main.app), primary
    return _make


def chat(client, content: str, conversation: str = "conv-1", stream: bool = False, tools=None):
    body = {"messages": [{"role": "system", "content": f"conversation_id: {conversation}"},
                         {"role": "user", "content": content}], "stream": stream}
    if tools:
        body["tools"] = tools
    return client.post("/v1/chat/completions", json=body, headers=AUTH)


def test_auth(make_client):
    client, _ = make_client(["hola"])
    with client:
        assert client.post("/v1/chat/completions", json={"messages": []}).status_code == 401
        assert client.get("/health").json()["status"] == "ok"


def test_sse_formato_openai(make_client):
    client, _ = make_client(["Hola, soy Sofía"])
    with client:
        resp = chat(client, "hola", stream=True)
        lines = [l for l in resp.text.splitlines() if l.startswith("data: ")]
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(l[6:]) for l in lines[:-1]]
    assert "".join(c["choices"][0]["delta"].get("content", "") for c in chunks).strip() == "Hola, soy Sofía"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_loop_de_tools_via_mcp(make_client):
    client, llm = make_client([
        [tool_call("verificar_paciente", dni="30111222", fecha_nacimiento="1985-04-12")],
        "Gracias María, ya te identifiqué.",
    ])
    with client:
        data = chat(client, "Mi DNI es 30111222 y nací el 12 de abril de 1985").json()
    summary = data["opsvoice"]
    assert summary["tool_calls"][0]["name"] == "verificar_paciente"
    assert json.loads(summary["tool_calls"][0]["result"])["ok"] is True
    assert "María" in data["choices"][0]["message"]["content"]
    # La 2.ª llamada al LLM ya ve el resultado de la tool.
    assert llm.calls[1][-1]["role"] == "tool"


def test_memoria_conserva_resultados_de_tools_entre_turnos(make_client):
    client, llm = make_client([[tool_call("listar_turnos", dni="30111222")], "Tenés un turno.", "Listo."])
    with client:
        chat(client, "¿qué turnos tengo?")
        chat(client, "cancelalo")  # ElevenLabs solo manda texto: el backend repone la tool del turno anterior
    assert any(m["role"] == "tool" for m in llm.calls[-1])


def test_tool_de_plataforma_se_devuelve_a_elevenlabs(make_client):
    end_call = {"type": "function", "function": {"name": "end_call", "parameters": {"type": "object", "properties": {}}}}
    client, _ = make_client([[tool_call("end_call")]])
    with client:
        data = chat(client, "chau, gracias", tools=[end_call]).json()
    assert data["choices"][0]["finish_reason"] == "tool_calls"
    assert data["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "end_call"


def test_dato_de_tarjeta_no_llega_al_llm(make_client):
    client, llm = make_client(["Por seguridad no tomo datos de tarjeta."])
    with client:
        data = chat(client, "te paso la tarjeta 4509 9535 6623 3704").json()
    assert "4509" not in json.dumps(llm.calls)
    assert data["opsvoice"]["guardrail_hits"] == 1


def test_presupuesto_agotado_corta_sin_llamar_al_llm(make_client):
    client, llm = make_client(["uno", "dos", "tres"])
    with client:
        budget = client.app.state.agent.budget
        budget.add("conv-caro", budget.budget_usd)
        data = chat(client, "hola", conversation="conv-caro").json()
    assert llm.calls == [] and data["opsvoice"]["budget_state"] == "exhausted"


def test_metrics(make_client):
    client, _ = make_client(["hola"])
    with client:
        chat(client, "hola")
        m = client.get("/metrics", headers=AUTH).json()
    assert m["turnos"] >= 1 and m["ttft_ms"]["p95"] is not None


def test_no_pega_frases_entre_llamadas_al_llm_ni_separa_tokens(make_client):
    client, _ = make_client([{"text": "Dame un segundo.", "tools": [tool_call("listar_turnos", dni="30111222")]},
                             "Tenés un turno el miércoles."])
    with client:
        text = chat(client, "¿qué turnos tengo?").json()["choices"][0]["message"]["content"]
    assert text == "Dame un segundo. Tenés un turno el miércoles. "
