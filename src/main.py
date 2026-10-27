"""API de OpsVoice (SCAFFOLD).

Ya funciona: arranque, carga del domain pack, conexión al server MCP, /health y la demo pública /demo.
Te toca (buscá los TODO [Cxx]):
    POST /v1/chat/completions   ← ElevenLabs Agents (Custom LLM) · streaming SSE compatible con OpenAI  [C16]
    autenticación Bearer con OPSVOICE_API_KEY                                                         [C16]
    POST /vision                ← documento del dominio → JSON validado                               [C19]
    GET  /metrics               ← latencia p50/p95, costo por conversación                            [C21]

Correr local:  uvicorn src.main:app --reload   →   http://localhost:8000/docs
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict

from mcp_server import store
from src.config import settings
from src.demo import render as render_demo
from src.domain import load_domain
from src.mcp_client import MCPToolbox

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("opsvoice")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.domain = load_domain(settings.domain)
    app.state.toolbox = MCPToolbox(settings.domain)
    await app.state.toolbox.start()
    # TODO [C18]: construir acá el harness y el agente, por ejemplo:
    #   router = LLMRouter([build_provider(s) for s in settings.llm_chain], build_provider(settings.llm_cheap),
    #                      settings.first_token_timeout_s)
    #   budget = BudgetTracker(app.state.domain.meta["presupuesto_usd_conversacion"], settings.budget_degrade_ratio)
    #   app.state.agent = Agent(app.state.domain, app.state.toolbox, router, budget, ConversationStore(),
    #                           settings.max_tool_iterations)
    #   app.state.limiter = RateLimiter(settings.rate_limit_per_minute)
    log.info("OpsVoice listo · dominio=%s · tools=%s", settings.domain, sorted(app.state.toolbox.names))
    yield
    await app.state.toolbox.close()


# Sin la telemetría propia de FastAPI: ElevenLabs manda `traceparent` con sampled=00 y, si FastAPI lo toma
# como contexto, los spans de Langfuse lo heredan y no se exportan.
app = FastAPI(title="OpsVoice", version="0.1.0", lifespan=lifespan,
              telemetry={"tracing": False, "metrics": False, "logs": False})


# TODO [C16]: dependencia `require_api_key` que valide el header `Authorization: Bearer <OPSVOICE_API_KEY>`
#             (usá fastapi.security.HTTPBearer y secrets.compare_digest). Aplicala a todos los endpoints
#             salvo /health.


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "domain": settings.domain}


@app.get("/demo", response_class=HTMLResponse)
async def demo(request: Request, campana: bool = False) -> str:
    """Página pública para hablar con el agente desde el navegador (widget de ElevenLabs). Ya viene hecha:
    necesita ELEVENLABS_AGENT_ID (el agente que configurás en C20)."""
    if not settings.elevenlabs_agent_id:
        raise HTTPException(503, "Falta ELEVENLABS_AGENT_ID: configurá el agente en ElevenLabs (C20)")
    return render_demo(request.app.state.domain, settings.elevenlabs_agent_id, campana)


@app.post("/admin/reset")
async def reset_mocks() -> dict:
    """Vuelve los mocks del negocio a los datos semilla (antes de una demo o de las simulaciones)."""
    store.reset(settings.domain)
    return {"status": "reset", "domain": settings.domain}


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")  # ElevenLabs manda campos extra

    messages: list[dict]
    stream: bool = True
    tools: list[dict] | None = None
    user: str | None = None


@app.post("/v1/chat/completions")
async def chat_completions(body: ChatRequest, request: Request):
    """Endpoint que ElevenLabs usa como LLM ("Custom LLM").

    TODO [C16]
    1. Obtener el conversation_id: header X-Conversation-Id, o la línea 'conversation_id: ...' que
       ElevenLabs pone en el system prompt (variable {{system__conversation_id}}), o body.user.
    2. Pasar los mensajes al agente (src/agent.py) y, a medida que genera texto, devolverlo como
       Server-Sent Events con el formato de OpenAI:
           data: {"id": ..., "object": "chat.completion.chunk", "choices": [{"index": 0,
                  "delta": {"content": "..."}, "finish_reason": null}]}\\n\\n
       Último chunk con finish_reason "stop" (o "tool_calls") y al final:  data: [DONE]\\n\\n
       Usá fastapi.responses.StreamingResponse(media_type="text/event-stream").
    3. Si body.stream es False, devolver un chat.completion normal (lo usa la suite de regresión) con un
       campo extra "opsvoice": {"tool_calls": [{"name", "arguments", "result"}], "cost_usd", "models"}.
    4. Si el LLM pide una tool que NO es del MCP (p. ej. end_call de ElevenLabs), devolverla como
       delta.tool_calls para que la ejecute la plataforma.
    """
    raise HTTPException(501, "TODO [C16]: implementar /v1/chat/completions")


@app.post("/vision")
async def vision(request: Request):
    """TODO [C19]: recibir `referencia` (Form) y `archivo` (UploadFile), validar tipo y tamaño, y llamar a
    vision.extractor.process_document(request.app.state.domain, referencia, bytes, content_type)."""
    raise HTTPException(501, "TODO [C19]: implementar /vision")


@app.get("/metrics")
async def get_metrics():
    """TODO [C21]: devolver src.observability.metrics.snapshot() (TTFT p50/p95, costo por conversación...)."""
    raise HTTPException(501, "TODO [C21]: implementar /metrics")
