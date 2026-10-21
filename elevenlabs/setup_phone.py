"""Importa el número de Twilio en ElevenLabs y lo asigna al agente del dominio (integración nativa).

    python elevenlabs/setup_phone.py clinica

Necesita en el .env: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER y el agente ya creado
(elevenlabs/agents/<dominio>.json o ELEVENLABS_AGENT_ID_<DOMINIO>).
Devuelve el phone_number_id → ELEVENLABS_PHONE_NUMBER_ID en Railway (para llamadas salientes).
Alternativa sin código: dashboard de ElevenLabs → Phone Numbers → Import number → Twilio.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from client import AGENTS_DIR, check, client


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("domain", choices=["clinica", "logistica", "cobranzas"])
    args = parser.parse_args()
    export_path = AGENTS_DIR / f"{args.domain}.json"
    agent_id = os.getenv(f"ELEVENLABS_AGENT_ID_{args.domain.upper()}") or (
        json.loads(export_path.read_text(encoding="utf-8"))["agent_id"] if export_path.exists() else None)
    if not agent_id:
        sys.exit("Primero exportá el agente: python elevenlabs/export_agent.py " + args.domain + " <agent_id>")
    missing = [v for v in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER") if not os.getenv(v)]
    if missing:
        sys.exit(f"Faltan en el .env: {', '.join(missing)}")

    with client() as http:
        resp = check(http.post("/v1/convai/phone-numbers", json={
            "provider": "twilio",
            "phone_number": os.environ["TWILIO_PHONE_NUMBER"],
            "label": f"OpsVoice {args.domain}",
            "sid": os.environ["TWILIO_ACCOUNT_SID"],
            "token": os.environ["TWILIO_AUTH_TOKEN"],
            "agent_id": agent_id,
        }))
    print(f"Número importado y asignado al agente {agent_id}")
    print(f"ELEVENLABS_PHONE_NUMBER_ID={resp['phone_number_id']}")


if __name__ == "__main__":
    main()
