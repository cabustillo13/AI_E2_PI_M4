"""Server MCP con las herramientas del negocio del dominio activo.

    DOMAIN=clinica python -m mcp_server.server        # transporte stdio

La API lo lanza como subproceso (stdio) al arrancar: un solo contenedor, sin un segundo deploy.
Para inspeccionarlo a mano:  DOMAIN=clinica mcp dev mcp_server/server.py
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # permite `mcp dev mcp_server/server.py`

from mcp.server.fastmcp import FastMCP  # noqa: E402

DOMAINS = ("clinica", "logistica", "cobranzas")


def build_server(domain: str) -> FastMCP:
    if domain not in DOMAINS:
        raise ValueError(f"DOMAIN inválido: {domain!r}. Opciones: {DOMAINS}")
    tools_module = importlib.import_module(f"mcp_server.tools.{domain}")
    mcp = FastMCP(f"opsvoice-{domain}", log_level="WARNING")
    for fn in tools_module.TOOLS:
        mcp.tool()(fn)  # nombre, descripción y schema salen de la firma y el docstring
    return mcp


if __name__ == "__main__":
    build_server(os.getenv("DOMAIN", "clinica")).run()  # stdio por defecto
