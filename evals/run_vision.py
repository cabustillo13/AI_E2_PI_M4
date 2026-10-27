"""Eval del sub-caso de visión contra el golden set (modelo de visión real).

    python -m evals.run_vision            # los 3 dominios
    python -m evals.run_vision clinica

Mide: acierto de status (valido / requiere_revision), exactitud por campo y costo por documento.
Reporte: evals/reports/vision.md
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
os.environ.update(OPSVOICE_TODAY="2026-11-02", DATA_DIR=tempfile.mkdtemp())
sys.path.insert(0, str(ROOT))

from src.domain import load_domain  # noqa: E402
from vision.extractor import process_document  # noqa: E402

SAMPLES = ROOT / "vision" / "samples"


async def run(domains: list[str]) -> list[dict]:
    golden = yaml.safe_load((ROOT / "evals" / "vision" / "expected.yaml").read_text(encoding="utf-8"))
    rows = []
    for domain_id in domains:
        domain = load_domain(domain_id)
        for case in golden[domain_id]:
            result = await process_document(domain, case["referencia"], (SAMPLES / case["archivo"]).read_bytes(),
                                            "image/png")
            campos_ok = {k: result["data"].get(k) == v for k, v in case["campos"].items()}
            rows.append({"archivo": case["archivo"], "status_ok": result["status"] == case["status"],
                         "status": result["status"], "campos_ok": campos_ok, "errores": result["errores"],
                         "intentos": result["intentos"], "costo_usd": result["costo_usd"], "modelo": result["modelo"]})
            mark = "✅" if rows[-1]["status_ok"] and all(campos_ok.values()) else "❌"
            print(f"{mark} {case['archivo']}: {result['status']} · campos {sum(campos_ok.values())}/{len(campos_ok)}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("domain", nargs="?", choices=["clinica", "logistica", "cobranzas"])
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    rows = asyncio.run(run([args.domain] if args.domain else ["clinica", "logistica", "cobranzas"]))
    total_campos = sum(len(r["campos_ok"]) for r in rows)
    campos_ok = sum(sum(r["campos_ok"].values()) for r in rows)
    lines = ["# Eval de visión", "",
             f"- Status correcto: **{sum(r['status_ok'] for r in rows)}/{len(rows)}**",
             f"- Exactitud de campos: **{campos_ok}/{total_campos}** ({campos_ok / total_campos:.0%})",
             f"- Costo promedio por documento: USD {sum(r['costo_usd'] for r in rows) / len(rows):.5f}", "",
             "| Documento | Status | Campos OK | Intentos | Errores detectados |", "|---|---|---|---|---|"]
    for r in rows:
        malos = [k for k, ok in r["campos_ok"].items() if not ok]
        lines.append(f"| {r['archivo']} | {'✅' if r['status_ok'] else '❌'} {r['status']} | "
                     f"{len(r['campos_ok']) - len(malos)}/{len(r['campos_ok'])}{' (falla: ' + ', '.join(malos) + ')' if malos else ''} | "
                     f"{r['intentos']} | {'; '.join(r['errores']) or '-'} |")
    out = ROOT / "evals" / "reports" / "vision.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReporte en {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
