"""Crea o actualiza el agente de ElevenLabs de un dominio a partir de domains/<id>.md.

    python elevenlabs/sync_agent.py clinica            # crea (o actualiza si ya existe el export)
    python elevenlabs/sync_agent.py clinica --export   # solo baja la config actual a agents/clinica.json

Qué configura:
- LLM = Custom LLM → PUBLIC_URL/v1 (nuestro backend), autenticado con OPSVOICE_API_KEY (secret de ElevenLabs).
- Idioma, primer mensaje y voz (del frontmatter).
- System prompt de *canal*: solo variables de la llamada. El comportamiento vive en el backend.
- Knowledge base: la sección '# Base de conocimiento' del domain pack.
- Tool de sistema end_call (la ejecuta ElevenLabs cuando el backend la pide).
- Evaluación post-llamada y recolección de datos (del frontmatter).
Los guardrails de plataforma se activan desde el dashboard (ver docs/SETUP_CUENTAS.md) y quedan en el export.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from client import AGENTS_DIR, check, client

from src.domain import load_domain

CHANNEL_PROMPT = """Canal: llamada de voz con {empresa}.
conversation_id: {{{{system__conversation_id}}}}
caller_id: {{{{system__caller_id}}}}
{extra}
(El comportamiento del agente lo define el backend OpsVoice: domains/{id}.md)"""


def build_config(domain, secret_id: str, kb_doc: dict) -> dict:
    meta = domain.meta
    public_url = os.getenv("PUBLIC_URL", "").rstrip("/")
    if not public_url:
        sys.exit("Falta PUBLIC_URL (URL pública del backend en Railway) en el .env")
    variables = meta.get("variables_dinamicas") or {}
    extra = "\n".join(f"{k}: {{{{{k}}}}}" for k in variables)
    agent = {
        "first_message": meta["primer_mensaje"],
        "language": meta["idioma"],
        "prompt": {
            "prompt": CHANNEL_PROMPT.format(empresa=meta["empresa"], id=domain.id, extra=extra),
            "llm": "custom-llm",
            "custom_llm": {"url": f"{public_url}/v1", "model_id": "opsvoice", "api_key": {"secret_id": secret_id}},
            "knowledge_base": [{"type": "text", "id": kb_doc["id"], "name": kb_doc["name"], "usage_mode": "auto"}],
            "built_in_tools": {"end_call": {"name": "end_call", "description": "",
                                            "params": {"system_tool_type": "end_call"}}},
        },
    }
    if variables:
        agent["dynamic_variables"] = {"dynamic_variable_placeholders": variables}
    tts = {"voice_id": meta["voz_elevenlabs"]} if meta.get("voz_elevenlabs") else {}
    return {
        "name": f"OpsVoice · {meta['empresa']}",
        "tags": ["opsvoice", domain.id],
        "conversation_config": {"agent": agent, **({"tts": tts} if tts else {})},
        "platform_settings": {
            "evaluation": {"criteria": [{"id": k, "name": k, "conversation_goal_prompt": v}
                                        for k, v in (meta.get("criterios_evaluacion") or {}).items()]},
            "data_collection": {k: {"type": "string", "description": v}
                                for k, v in (meta.get("datos_a_recolectar") or {}).items()},
        },
    }


def export(http, domain_id: str, agent_id: str) -> None:
    config = check(http.get(f"/v1/convai/agents/{agent_id}"))
    AGENTS_DIR.mkdir(exist_ok=True)
    path = AGENTS_DIR / f"{domain_id}.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Export guardado en {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("domain", choices=["clinica", "logistica", "cobranzas"])
    parser.add_argument("--export", action="store_true", help="solo exportar la config actual")
    args = parser.parse_args()
    domain = load_domain(args.domain)
    export_path = AGENTS_DIR / f"{args.domain}.json"
    agent_id = os.getenv(f"ELEVENLABS_AGENT_ID_{args.domain.upper()}") or (
        json.loads(export_path.read_text(encoding="utf-8"))["agent_id"] if export_path.exists() else None)

    with client() as http:
        if args.export:
            if not agent_id:
                sys.exit("No hay agent_id para exportar")
            return export(http, args.domain, agent_id)

        api_key = os.getenv("OPSVOICE_API_KEY") or sys.exit("Falta OPSVOICE_API_KEY en el .env")
        secret = check(http.post("/v1/convai/secrets",
                                 json={"type": "new", "name": f"opsvoice-{args.domain}-api-key", "value": api_key}))
        kb_doc = check(http.post("/v1/convai/knowledge-base/text",
                                 json={"name": f"KB {domain.meta['empresa']}", "text": domain.knowledge_base}))
        config = build_config(domain, secret["secret_id"], kb_doc)

        if agent_id:
            check(http.patch(f"/v1/convai/agents/{agent_id}", json=config))
            print(f"Agente actualizado: {agent_id}")
        else:
            agent_id = check(http.post("/v1/convai/agents/create", json=config))["agent_id"]
            print(f"Agente creado: {agent_id}  →  guardalo como ELEVENLABS_AGENT_ID en Railway")
        export(http, args.domain, agent_id)


if __name__ == "__main__":
    main()
