"""Domain packs y traducción de mensajes entre formatos de proveedor."""

import pytest

from src.domain import load_domain
from src.llm.providers import to_anthropic


@pytest.mark.parametrize("domain_id", ["clinica", "logistica", "cobranzas"])
def test_domain_packs_cargan(domain_id):
    domain = load_domain(domain_id)
    prompt = domain.system_prompt()
    assert domain.meta["empresa"] in prompt
    assert "2026-11-02 (lunes)" in prompt          # 'hoy' se inyecta en las reglas comunes
    assert domain.knowledge_base.startswith("# Base de conocimiento")
    assert domain.meta["criterios_evaluacion"]


def test_chat_completions_a_anthropic():
    messages = [
        {"role": "system", "content": "sos Sofía"},
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "Dame un segundo.", "tool_calls": [
            {"id": "t1", "type": "function", "function": {"name": "listar_turnos", "arguments": '{"dni": "1"}'}},
            {"id": "t2", "type": "function", "function": {"name": "consultar_orden_medica", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "{}"},
        {"role": "tool", "tool_call_id": "t2", "content": "{}"},
    ]
    system, out = to_anthropic(messages)
    assert system == "sos Sofía"
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert out[1]["content"][1] == {"type": "tool_use", "id": "t1", "name": "listar_turnos", "input": {"dni": "1"}}
    assert [b["tool_use_id"] for b in out[2]["content"]] == ["t1", "t2"]  # resultados en un solo mensaje


def test_anthropic_empieza_con_user_aunque_hable_primero_el_agente():
    _, out = to_anthropic([{"role": "assistant", "content": "Hola, soy Sofía"}, {"role": "user", "content": "hola"}])
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
