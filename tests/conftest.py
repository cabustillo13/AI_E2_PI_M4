"""Fixtures comunes. Los tests NO llaman a ningún LLM real: corren en CI sin claves."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Fecha fija y datos aislados para todos los tests (antes de importar código del proyecto).
os.environ["OPSVOICE_TODAY"] = "2026-11-02"  # lunes
os.environ.setdefault("OPSVOICE_API_KEY", "test-key")
# Los tests no mandan trazas a Langfuse aunque el .env tenga claves.
os.environ["LANGFUSE_PUBLIC_KEY"] = os.environ["LANGFUSE_SECRET_KEY"] = ""


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    from mcp_server import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))  # para el subproceso MCP
    yield tmp_path
