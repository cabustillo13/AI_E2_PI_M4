"""Cliente MCP: lanza mcp_server como subproceso (stdio) y expone sus tools al agente."""

from __future__ import annotations

import json
import os
import sys
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.config import ROOT


class MCPToolbox:
    def __init__(self, domain: str):
        self.domain = domain
        self._stack = AsyncExitStack()
        self.session: ClientSession | None = None
        self.openai_tools: list[dict] = []

    async def start(self) -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_server.server"],
            env={**os.environ, "DOMAIN": self.domain},
            cwd=str(ROOT),
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        listed = await self.session.list_tools()
        # Las tools MCP se exponen al LLM en formato function-calling de OpenAI (formato interno).
        self.openai_tools = [
            {"type": "function", "function": {"name": t.name, "description": t.description or "",
                                              "parameters": t.inputSchema}}
            for t in listed.tools
        ]

    @property
    def names(self) -> set[str]:
        return {t["function"]["name"] for t in self.openai_tools}

    async def call(self, name: str, arguments: dict) -> str:
        result = await self.session.call_tool(name, arguments)
        text = "".join(c.text for c in result.content if getattr(c, "type", "") == "text")
        if result.isError:
            # Error de ejecución (args inválidos, excepción): se le devuelve al LLM para que se corrija.
            return json.dumps({"ok": False, "error": text or "Error ejecutando la herramienta"}, ensure_ascii=False)
        return text

    async def close(self) -> None:
        await self._stack.aclose()
