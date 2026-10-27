"""Exporta la configuración de tu agente de ElevenLabs a elevenlabs/agents/<dominio>.json (entregable).

    python elevenlabs/export_agent.py clinica      # usa ELEVENLABS_AGENT_ID del .env

El agente lo configurás vos en C20 (dashboard o API): voz, idioma, primer mensaje, Custom LLM apuntando
a PUBLIC_URL/v1 con tu OPSVOICE_API_KEY, knowledge base, guardrails y evaluación post-llamada.
Tip: el system prompt de ElevenLabs puede incluir `conversation_id: {{system__conversation_id}}` para
que tu backend sepa qué conversación es.
"""

from __future__ import annotations

import argparse
import json

from client import AGENTS_DIR, agent_id, check, client


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("domain", choices=["clinica", "logistica", "cobranzas"])
    args = parser.parse_args()
    with client() as http:
        config = check(http.get(f"/v1/convai/agents/{agent_id()}"))
    AGENTS_DIR.mkdir(exist_ok=True)
    path = AGENTS_DIR / f"{args.domain}.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Export guardado en {path}")


if __name__ == "__main__":
    main()
