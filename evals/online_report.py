"""Monitoreo online: métricas de negocio del agente en producción + costo cada 1.000 conversaciones.

    python -m evals.online_report clinica

Junta tres fuentes:
- ElevenLabs (GET /v1/convai/conversations): llamadas, duración y resultado de la evaluación post-llamada.
- Backend (GET /metrics): latencia TTFT p50/p95, costo LLM por conversación, eventos del harness.
- Precios de voz y telefonía (variables de entorno, revisalos según tu plan).
Las trazas detalladas de cada turno están en Langfuse (sesión = conversation_id).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "elevenlabs"))
from client import AGENTS_DIR, check, client  # noqa: E402

# USD por minuto: dependen del plan contratado. Defaults de referencia, actualizalos.
VOICE_USD_PER_MIN = float(os.getenv("ELEVENLABS_USD_PER_MIN", "0.10"))
PHONE_USD_PER_MIN = float(os.getenv("TWILIO_USD_PER_MIN", "0.0085"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("domain", choices=["clinica", "logistica", "cobranzas"])
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    export = AGENTS_DIR / f"{args.domain}.json"
    agent_id = os.getenv(f"ELEVENLABS_AGENT_ID_{args.domain.upper()}") or json.loads(
        export.read_text(encoding="utf-8"))["agent_id"]

    with client() as http:
        convs = check(http.get("/v1/convai/conversations", params={"agent_id": agent_id, "page_size": 100}))
    convs = convs.get("conversations", [])
    backend = httpx.get(f"{os.environ['PUBLIC_URL'].rstrip('/')}/metrics",
                        headers={"Authorization": f"Bearer {os.environ['OPSVOICE_API_KEY']}"}, timeout=30).json()

    durations = [c.get("call_duration_secs") or 0 for c in convs]
    resueltas = sum(c.get("call_successful") == "success" for c in convs)
    minutos = statistics.mean(durations) / 60 if durations else 0
    llm = backend.get("costo_usd_promedio_conversacion") or 0
    por_conv = llm + minutos * (VOICE_USD_PER_MIN + PHONE_USD_PER_MIN)
    p95_dur = statistics.quantiles(durations, n=100, method="inclusive")[94] if len(durations) > 1 else (durations or [0])[0]

    lines = [f"# Monitoreo online · {args.domain}", "",
             "## Negocio (ElevenLabs)", "",
             f"- Conversaciones: **{len(convs)}**",
             f"- Resolución (evaluación post-llamada = success): **{resueltas}/{len(convs)}**"
             + (f" ({resueltas / len(convs):.0%})" if convs else ""),
             f"- Duración promedio: {minutos:.1f} min · p95: {p95_dur / 60:.1f} min",
             *(["", "> Sin llamadas reales todavía (las simulaciones de la testing suite no cuentan como "
                "conversaciones): el costo de voz y telefonía queda en 0 hasta que haya llamadas."] if not convs else []),
             "",
             "## Técnico (backend)", "",
             f"- TTFT p50 / p95: {backend['ttft_ms']['p50']} / {backend['ttft_ms']['p95']} ms",
             f"- Turno completo p50 / p95: {backend['turno_ms']['p50']} / {backend['turno_ms']['p95']} ms",
             f"- Eventos del harness: {backend['eventos'] or 'ninguno'}", "",
             "## Costo estimado", "",
             "| Concepto | USD por conversación | USD cada 1.000 |", "|---|---|---|",
             f"| LLM (medido) | {llm:.4f} | {llm * 1000:.2f} |",
             f"| Voz ElevenLabs ({VOICE_USD_PER_MIN}/min) | {minutos * VOICE_USD_PER_MIN:.4f} | {minutos * VOICE_USD_PER_MIN * 1000:.2f} |",
             f"| Telefonía Twilio ({PHONE_USD_PER_MIN}/min) | {minutos * PHONE_USD_PER_MIN:.4f} | {minutos * PHONE_USD_PER_MIN * 1000:.2f} |",
             f"| **Total** | **{por_conv:.4f}** | **{por_conv * 1000:.2f}** |"]
    out = ROOT / "evals" / "reports" / f"online_{args.domain}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
