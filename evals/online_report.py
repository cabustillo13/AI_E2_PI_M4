"""Monitoreo online: métricas de negocio del agente en producción + costo cada 1.000 conversaciones.

    python -m evals.online_report clinica

Junta dos fuentes, ambas medidas (nada estimado):
- ElevenLabs (conversaciones reales): duración, evaluación post-llamada y lo que cobró la plataforma
  por cada una (voz: STT + TTS, y los modelos propios que usa para turnos y análisis).
- Backend (GET /metrics): latencia TTFT p50/p95, costo de nuestro LLM por conversación, eventos del harness.
Las trazas detalladas de cada turno están en Langfuse (sesión = conversation_id).
Las simulaciones de la testing suite no cuentan como conversaciones.
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


def p95(values: list[float]) -> float:
    if len(values) > 1:
        return statistics.quantiles(values, n=100, method="inclusive")[94]
    return values[0] if values else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("domain", choices=["clinica", "logistica", "cobranzas"])
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    agent_id = json.loads((AGENTS_DIR / f"{args.domain}.json").read_text(encoding="utf-8"))["agent_id"]

    with client() as http:
        listed = check(http.get("/v1/convai/conversations", params={"agent_id": agent_id, "page_size": 100}))
        details = [check(http.get(f"/v1/convai/conversations/{c['conversation_id']}"))
                   for c in listed.get("conversations", [])]
    backend = httpx.get(f"{os.environ['PUBLIC_URL'].rstrip('/')}/metrics",
                        headers={"Authorization": f"Bearer {os.environ['OPSVOICE_API_KEY']}"}, timeout=30).json()

    n = len(details)
    durations = [(d.get("metadata") or {}).get("call_duration_secs") or 0 for d in details]
    charging = [(d.get("metadata") or {}).get("charging") or {} for d in details]
    voz = [c.get("platform_price") or 0 for c in charging]
    llm_plataforma = [c.get("llm_price") or 0 for c in charging]
    resueltas = sum((d.get("analysis") or {}).get("call_successful") == "success" for d in details)
    mean = lambda xs: statistics.mean(xs) if xs else 0.0  # noqa: E731
    llm_backend = backend.get("costo_usd_promedio_conversacion") or 0
    total = mean(voz) + mean(llm_plataforma) + llm_backend
    minutos = mean(durations) / 60

    lines = [f"# Monitoreo online · {args.domain}", "",
             "## Negocio (ElevenLabs)", "",
             f"- Conversaciones: **{n}**",
             f"- Resolución (evaluación post-llamada = success): **{resueltas}/{n}**"
             + (f" ({resueltas / n:.0%})" if n else ""),
             f"- Duración promedio: {minutos:.1f} min · p95: {p95(durations) / 60:.1f} min", "",
             "## Técnico (backend)", "",
             f"- TTFT p50 / p95: {backend['ttft_ms']['p50']} / {backend['ttft_ms']['p95']} ms",
             f"- Turno completo p50 / p95: {backend['turno_ms']['p50']} / {backend['turno_ms']['p95']} ms",
             f"- Eventos del harness: {backend['eventos'] or 'ninguno'}", "",
             "## Costo medido", "",
             "| Concepto | USD por conversación | USD cada 1.000 |", "|---|---|---|",
             f"| Voz ElevenLabs (STT + TTS) | {mean(voz):.4f} | {mean(voz) * 1000:.2f} |",
             f"| Modelos de la plataforma (turnos, análisis) | {mean(llm_plataforma):.4f} | {mean(llm_plataforma) * 1000:.2f} |",
             f"| LLM del backend | {llm_backend:.4f} | {llm_backend * 1000:.2f} |",
             f"| **Total** | **{total:.4f}** | **{total * 1000:.2f}** |",
             "", f"Costo de voz por minuto: USD {mean(voz) / minutos:.3f}" if minutos else ""]
    out = ROOT / "evals" / "reports" / f"online_{args.domain}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
