"""Corre las conversaciones simuladas en la testing suite de ElevenLabs y guarda el reporte.

    python -m evals.run_simulations clinica

1. Crea (una sola vez) un test de tipo "simulation" por escenario y guarda los ids en
   evals/simulations/test_ids_<dominio>.json.
2. Los corre contra el agente (que llama a nuestro backend desplegado).
3. Espera los resultados y escribe evals/reports/simulations_<dominio>.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "elevenlabs"))
from client import agent_id as get_agent_id, check, client  # noqa: E402

SIMS = ROOT / "evals" / "simulations"
REPORTS = ROOT / "evals" / "reports"


def ensure_tests(http, domain: str, agent_id: str, suite: dict) -> dict[str, str]:
    """Los tests viven en la cuenta del agente: si el agente cambió (otra cuenta), se crean de nuevo."""
    ids_path = SIMS / f"test_ids_{domain}.json"
    saved = json.loads(ids_path.read_text(encoding="utf-8")) if ids_path.exists() else {}
    ids = saved.get("tests", {}) if saved.get("agent_id") == agent_id else {}
    for esc in suite["escenarios"]:
        if esc["id"] in ids:
            continue
        resp = check(http.post("/v1/convai/agent-testing/create", json={
            "name": f"{domain}:{esc['id']}",
            "type": "simulation",
            "simulation_scenario": esc["escenario"],
            "success_conditions": esc["exito"],
            "simulation_max_turns": suite.get("max_turnos", 10),
        }))
        ids[esc["id"]] = resp["id"]
        print(f"test creado {esc['id']} → {resp['id']}")
    ids_path.write_text(json.dumps({"agent_id": agent_id, "tests": ids}, indent=2), encoding="utf-8")
    return ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("domain", choices=["clinica", "logistica", "cobranzas"])
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    suite = yaml.safe_load((SIMS / f"{args.domain}.yaml").read_text(encoding="utf-8"))
    agent_id = get_agent_id()

    # Mocks a datos semilla para que cada corrida parta del mismo estado.
    public_url, api_key = os.getenv("PUBLIC_URL", "").rstrip("/"), os.getenv("OPSVOICE_API_KEY", "")
    if public_url and api_key:
        httpx.post(f"{public_url}/admin/reset", headers={"Authorization": f"Bearer {api_key}"}, timeout=30)

    with client() as http:
        ids = ensure_tests(http, args.domain, agent_id, suite)
        invocation = check(http.post(f"/v1/convai/agents/{agent_id}/run-tests",
                                     json={"tests": [{"test_id": ids[e["id"]]} for e in suite["escenarios"]]}))
        print(f"Corriendo {len(ids)} simulaciones (invocación {invocation['id']})...")
        while True:
            result = check(http.get(f"/v1/convai/test-invocations/{invocation['id']}"))
            pending = sum(r["status"] == "pending" for r in result["test_runs"])
            if not pending:
                break
            print(f"  {pending} pendientes...")
            time.sleep(10)

    by_id = {v: k for k, v in ids.items()}
    runs = sorted(result["test_runs"], key=lambda r: by_id.get(r["test_id"], ""))
    passed = sum(r["status"] == "passed" for r in runs)
    lines = [f"# Simulaciones ElevenLabs · {args.domain}", "",
             f"- Aprobadas: **{passed}/{len(runs)}** ({passed / len(runs):.0%})",
             f"- Invocación: `{invocation['id']}` · agente `{agent_id}`", "",
             "| Escenario | Resultado | Resumen del evaluador |", "|---|---|---|"]
    for r in runs:
        summary = ((r.get("condition_result") or {}).get("rationale") or {}).get("summary", "")
        lines.append(f"| {by_id.get(r['test_id'], r['test_id'])} | {'✅' if r['status'] == 'passed' else '❌'} "
                     f"| {summary.replace('|', '/')} |")
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"simulations_{args.domain}.md").write_text("\n".join(lines), encoding="utf-8")
    (REPORTS / f"simulations_{args.domain}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                                            encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
