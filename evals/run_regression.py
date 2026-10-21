"""Suite de regresión pre-deploy (texto, LLM real).

    python -m evals.run_regression clinica                 # in-process, mocks aislados y fecha fija
    python -m evals.run_regression clinica --url https://opsvoice-clinica.up.railway.app   # contra prod

Sale con código 1 si la tasa de aprobación queda debajo del umbral del YAML → sirve de gate en CI.
Reporte: evals/reports/regression_<dominio>.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "evals" / "reports"
FECHA_EVALS = "2026-11-02"


def _ok(result: str) -> bool:
    try:
        return json.loads(result).get("ok") is True
    except (json.JSONDecodeError, AttributeError):
        return False


def check_case(case: dict, answers: list[str], tool_calls: list[dict]) -> list[str]:
    """Devuelve la lista de fallas (vacía = aprobado)."""
    fallas = []
    ok_tools = {t["name"] for t in tool_calls if _ok(t["result"])}
    called = {t["name"] for t in tool_calls}
    text = "\n".join(answers)
    for name in case.get("tools_exitosas", []):
        if name not in ok_tools:
            fallas.append(f"no se llamó con éxito a {name}")
    for name in case.get("tools_prohibidas", []):
        if name in called:
            fallas.append(f"llamó a la tool prohibida {name}")
    for pattern in case.get("debe_decir", []):
        if not re.search(pattern, text):
            fallas.append(f"no dijo /{pattern}/")
    for pattern in case.get("no_debe_decir", []):
        if m := re.search(pattern, text):
            fallas.append(f"dijo lo prohibido '{m.group()}'")
    return fallas


def run_case(post, case: dict) -> dict:
    conv = f"reg-{case['id']}-{uuid.uuid4().hex[:6]}"
    history: list[dict] = []
    answers, tool_calls, latencies, cost, models = [], [], [], 0.0, set()
    for user_text in case["turnos"]:
        history.append({"role": "user", "content": user_text})
        start = time.perf_counter()
        resp = post({"messages": [{"role": "system", "content": f"conversation_id: {conv}"}, *history],
                     "stream": False}, conv)
        latencies.append((time.perf_counter() - start) * 1000)
        answer = resp["choices"][0]["message"]["content"]
        summary = resp.get("opsvoice") or {}
        answers.append(answer)
        tool_calls += summary.get("tool_calls", [])
        cost += summary.get("cost_usd", 0.0)
        models |= set(summary.get("models", []))
        history.append({"role": "assistant", "content": answer})
    fallas = check_case(case, answers, tool_calls)
    return {"id": case["id"], "aprobado": not fallas, "fallas": fallas, "costo_usd": cost,
            "latencia_ms_max": max(latencies), "latencias_ms": latencies, "modelos": sorted(models),
            "transcript": [m for m in history], "tools": [t["name"] for t in tool_calls]}


def write_report(domain: str, suite: dict, results: list[dict]) -> float:
    REPORTS.mkdir(parents=True, exist_ok=True)
    rate = sum(r["aprobado"] for r in results) / len(results)
    lat = [l for r in results for l in r["latencias_ms"]]
    p95 = statistics.quantiles(lat, n=100, method="inclusive")[94] if len(lat) > 1 else lat[0]
    lines = [f"# Regresión · {domain}", "",
             f"- Aprobación: **{rate:.0%}** ({sum(r['aprobado'] for r in results)}/{len(results)}) · "
             f"umbral {suite['umbral_aprobacion']:.0%} → {'✅ PASA' if rate >= suite['umbral_aprobacion'] else '❌ NO PASA'}",
             f"- Costo total LLM: USD {sum(r['costo_usd'] for r in results):.4f}",
             f"- Latencia por turno (texto, sin voz): p95 {p95:.0f} ms", "",
             "| Caso | Resultado | Tools llamadas | Costo USD | Fallas |", "|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['id']} | {'✅' if r['aprobado'] else '❌'} | {', '.join(r['tools']) or '—'} | "
                     f"{r['costo_usd']:.4f} | {'; '.join(r['fallas']) or '—'} |")
    lines += ["", "## Transcripts de los casos fallidos", ""]
    for r in [r for r in results if not r["aprobado"]]:
        lines.append(f"### {r['id']}")
        lines += [f"- **{m['role']}**: {m['content']}" for m in r["transcript"]]
        lines.append("")
    (REPORTS / f"regression_{domain}.md").write_text("\n".join(lines), encoding="utf-8")
    (REPORTS / f"regression_{domain}.json").write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                                       encoding="utf-8")
    return rate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("domain", choices=["clinica", "logistica", "cobranzas"])
    parser.add_argument("--url", help="URL del servicio desplegado (por defecto: in-process)")
    parser.add_argument("--caso", help="correr un solo caso por id")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    suite = yaml.safe_load((ROOT / "evals" / "regression" / f"{args.domain}.yaml").read_text(encoding="utf-8"))
    cases = [c for c in suite["casos"] if not args.caso or c["id"] == args.caso]

    if args.url:
        key = os.environ["OPSVOICE_API_KEY"]
        http = httpx.Client(base_url=args.url, timeout=90, headers={"Authorization": f"Bearer {key}"})

        def post(body, conv):
            r = http.post("/v1/chat/completions", json=body, headers={"X-Conversation-Id": conv})
            r.raise_for_status()
            return r.json()
        results = [run_case(post, c) for c in cases]
    else:
        # In-process: mismos mocks semilla en cada caso y fecha fija → resultados comparables entre corridas.
        os.environ.update(DOMAIN=args.domain, OPSVOICE_TODAY=FECHA_EVALS, DATA_DIR=tempfile.mkdtemp(),
                          OPSVOICE_API_KEY=os.getenv("OPSVOICE_API_KEY") or "eval-key")
        sys.path.insert(0, str(ROOT))
        from fastapi.testclient import TestClient

        from mcp_server import store
        from src.main import app

        store.DATA_DIR = Path(os.environ["DATA_DIR"])
        results = []
        with TestClient(app) as client:
            def post(body, conv):
                r = client.post("/v1/chat/completions", json=body,
                                headers={"Authorization": f"Bearer {os.environ['OPSVOICE_API_KEY']}",
                                         "X-Conversation-Id": conv})
                r.raise_for_status()
                return r.json()
            for case in cases:
                store.reset(args.domain)
                results.append(run_case(post, case))
                print(f"{'✅' if results[-1]['aprobado'] else '❌'} {case['id']}  {results[-1]['fallas'] or ''}")

    rate = write_report(args.domain, suite, results)
    print(f"\nAprobación {rate:.0%} · reporte en evals/reports/regression_{args.domain}.md")
    sys.exit(0 if rate >= suite["umbral_aprobacion"] else 1)


if __name__ == "__main__":
    main()
