"""Crea o actualiza el agente de ElevenLabs de un dominio a partir de domains/<id>.md.

    python elevenlabs/sync_agent.py clinica            # crea (o actualiza si ya existe el export)
    python elevenlabs/sync_agent.py clinica --export   # solo baja la config actual a agents/clinica.json

Qué configura:
- LLM = Custom LLM → PUBLIC_URL/v1 (nuestro backend), autenticado con OPSVOICE_API_KEY (secret de ElevenLabs).
- Idioma, primer mensaje y voz (del frontmatter).
- System prompt de *canal*: solo variables de la llamada. El comportamiento vive en el backend.
- Knowledge base: la sección '# Base de conocimiento' del domain pack.
- Tool de sistema end_call (la ejecuta ElevenLabs cuando el backend la pide).
- Duración máxima de la llamada (del frontmatter): la voz es ~85 % del costo y /demo es pública.
- Evaluación post-llamada y recolección de datos (del frontmatter).
- Guardrails de plataforma: foco en el rol, prompt injection, contenido dañino y uno custom de datos de pago.
- Acceso: público para el widget de GET /demo, restringido a PUBLIC_URL y localhost.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import urlparse

from client import AGENTS_DIR, check, client

from src.domain import load_domain

# Guardrails de la plataforma (capa extra a los del backend). "medical_and_legal_information" queda apagado:
# en la clínica cortaría llamadas legítimas cuando el paciente describe síntomas; eso lo maneja el prompt.
GUARDRAILS = {
    "version": "1",
    "focus": {"is_enabled": True},
    "prompt_injection": {"is_enabled": True},
    "content": {"config": {k: {"is_enabled": True, "threshold": "medium"}
                           for k in ("sexual", "violence", "harassment", "self_harm")}},
    "custom": {"config": {"configs": [{
        "name": "sin_datos_de_pago",
        # Acotado a propósito: uno genérico de "datos sensibles" corta la conversación al pedir el DNI.
        "prompt": ("Bloquear SOLO si el agente pide, repite o confirma un número de tarjeta de crédito o débito, "
                   "un CBU/CVU, un código de seguridad (CVV) o una contraseña. Pedir o repetir DNI, fecha de "
                   "nacimiento, código de seguimiento, número de turno o de cuenta es normal: NO bloquear."),
        "is_enabled": True,
    }]}},
}

CHANNEL_PROMPT = """Canal: conversación de voz con {empresa} (widget web).
conversation_id: {{{{system__conversation_id}}}}
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
        "conversation_config": {"agent": agent, **({"tts": tts} if tts else {}),
                                "conversation": {"max_duration_seconds": meta["duracion_max_llamada_s"]}},
        "platform_settings": {
            # Agente público (lo usa el widget de /demo) pero solo desde nuestro dominio y localhost.
            "auth": {"enable_auth": False,
                     "allowlist": [{"hostname": urlparse(public_url).hostname}, {"hostname": "localhost"}]},
            "evaluation": {"criteria": [{"id": k, "name": k, "conversation_goal_prompt": v}
                                        for k, v in (meta.get("criterios_evaluacion") or {}).items()]},
            "data_collection": {k: {"type": "string", "description": v}
                                for k, v in (meta.get("datos_a_recolectar") or {}).items()},
            "guardrails": GUARDRAILS,
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
    agent_id = os.getenv("ELEVENLABS_AGENT_ID", "").strip() or None
    exported = json.loads(export_path.read_text(encoding="utf-8")).get("agent_id") if export_path.exists() else None
    if not agent_id and exported and not args.export:
        # Evita crear un agente duplicado por no haber cargado el id del agente ya creado.
        sys.exit(f"Ya existe el agente {exported} (export en {export_path.name}): cargalo en ELEVENLABS_AGENT_ID "
                 "para actualizarlo, o borrá el export para crear uno nuevo.")

    with client() as http:
        if args.export:
            if not agent_id:
                sys.exit("Falta ELEVENLABS_AGENT_ID en el .env")
            return export(http, args.domain, agent_id)

        api_key = os.getenv("OPSVOICE_API_KEY") or sys.exit("Falta OPSVOICE_API_KEY en el .env")
        previous = json.loads(export_path.read_text(encoding="utf-8")) if export_path.exists() else {}
        if agent_id and http.get(f"/v1/convai/agents/{agent_id}").status_code == 404:
            # El agente (y su secret) son de otra cuenta: la voz la cobra la cuenta dueña del agente,
            # así que con una API key nueva se crea un agente nuevo en esa cuenta.
            print(f"El agente {agent_id} no existe en la cuenta de ELEVENLABS_API_KEY: se crea uno nuevo.")
            agent_id, previous = None, {}
        secret_id = (previous.get("conversation_config", {}).get("agent", {}).get("prompt", {})
                     .get("custom_llm", {}) or {}).get("api_key", {}).get("secret_id")
        if not secret_id:  # al actualizar se reutiliza el secret; se crea solo con el agente
            secret_id = check(http.post("/v1/convai/secrets", json={
                "type": "new", "name": f"opsvoice-{args.domain}-api-key", "value": api_key}))["secret_id"]
        kb_doc = check(http.post("/v1/convai/knowledge-base/text",
                                 json={"name": f"KB {domain.meta['empresa']}", "text": domain.knowledge_base}))
        config = build_config(domain, secret_id, kb_doc)

        if agent_id:
            check(http.patch(f"/v1/convai/agents/{agent_id}", json=config))
            print(f"Agente actualizado: {agent_id}")
        else:
            agent_id = check(http.post("/v1/convai/agents/create", json=config))["agent_id"]
            print(f"Agente creado: {agent_id}  →  cargalo como ELEVENLABS_AGENT_ID en Railway y en el .env")
        export(http, args.domain, agent_id)


if __name__ == "__main__":
    main()
