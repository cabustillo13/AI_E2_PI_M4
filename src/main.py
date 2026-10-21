"""API de OpsVoice.

    POST /v1/chat/completions   ← ElevenLabs Agents (Custom LLM) · streaming SSE compatible con OpenAI
    POST /vision                ← subida del documento del dominio → JSON validado
    POST /calls/outbound        ← dispara una llamada saliente (campañas de cobranzas)
    GET  /metrics               ← latencia p50/p95, costo por conversación, eventos del harness
    GET  /health                ← healthcheck de Railway

Correr local:  uvicorn src.main:app --reload
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

from mcp_server import store
from src.agent import Agent, ToolCallsOut, TurnContext, TurnSummary
from src.config import settings
from src.domain import load_domain
from src.harness.budget import BudgetTracker
from src.harness.rate_limit import RateLimiter
from src.harness.router import LLMRouter
from src.llm.providers import TextDelta, build_provider
from src.mcp_client import MCPToolbox
from src.memory import ConversationStore
from src.observability import flush, metrics
from vision.extractor import VisionError, process_document

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("opsvoice")


@asynccontextmanager
async def lifespan(app: FastAPI):
    domain = load_domain(settings.domain)
    toolbox = MCPToolbox(settings.domain)
    await toolbox.start()
    router = LLMRouter(
        chain=[build_provider(s) for s in settings.llm_chain],
        cheap=build_provider(settings.llm_cheap),
        first_token_timeout_s=settings.first_token_timeout_s,
        on_fallback=lambda frm, err: metrics.counters.update(["fallback_de_modelo"]),
    )
    app.state.domain = domain
    app.state.agent = Agent(domain, toolbox, router, BudgetTracker(domain.meta["presupuesto_usd_conversacion"],
                                                                     settings.budget_degrade_ratio),
                            ConversationStore(), settings.max_tool_iterations)
    app.state.limiter = RateLimiter(settings.rate_limit_per_minute)
    log.info("OpsVoice listo · dominio=%s · tools=%s", domain.id, sorted(toolbox.names))
    yield
    await toolbox.close()
    flush()


app = FastAPI(title="OpsVoice", version="1.0.0", lifespan=lifespan)
bearer = HTTPBearer(auto_error=False)


def require_api_key(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    if not settings.api_key:
        raise HTTPException(500, "Falta configurar OPSVOICE_API_KEY en el servidor")
    if creds is None or not secrets.compare_digest(creds.credentials, settings.api_key):
        raise HTTPException(401, "API key inválida", headers={"WWW-Authenticate": "Bearer"})


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Error no controlado en %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": "internal_error"})


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "domain": settings.domain}


@app.get("/metrics", dependencies=[Depends(require_api_key)])
async def get_metrics() -> dict:
    return {"domain": settings.domain, **metrics.snapshot()}


@app.post("/admin/reset", dependencies=[Depends(require_api_key)])
async def reset_mocks() -> dict:
    """Vuelve los mocks del negocio a los datos semilla (antes de una demo o de las simulaciones)."""
    store.reset(settings.domain)
    return {"status": "reset", "domain": settings.domain}


# ─────────────────────────── Custom LLM para ElevenLabs ───────────────────────────


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")  # ElevenLabs manda campos extra (elevenlabs_extra_body, etc.)

    messages: list[dict]
    stream: bool = True
    tools: list[dict] | None = None
    user: str | None = None


def conversation_id(body: ChatRequest, request: Request) -> str:
    """El system prompt de ElevenLabs incluye 'conversation_id: {{system__conversation_id}}'."""
    if header := request.headers.get("x-conversation-id"):
        return header
    system = next((m.get("content") or "" for m in body.messages if m["role"] == "system"), "")
    if (m := re.search(r"conversation_id:\s*([\w-]+)", system)) and "{{" not in m.group(1):
        return m.group(1)
    return body.user or f"anon-{uuid.uuid4().hex[:12]}"


def _chunk(cid: str, delta: dict, finish: str | None = None) -> str:
    payload = {"id": f"chatcmpl-{cid}", "object": "chat.completion.chunk", "created": int(time.time()),
               "model": "opsvoice", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/v1/chat/completions", dependencies=[Depends(require_api_key)])
async def chat_completions(body: ChatRequest, request: Request):
    cid = conversation_id(body, request)
    if not request.app.state.limiter.allow(cid):
        metrics.counters["rate_limited"] += 1
        raise HTTPException(429, "Demasiadas solicitudes para esta conversación")

    system_in = next((m.get("content") or "" for m in body.messages if m["role"] == "system"), "")
    ctx = TurnContext(conversation_id=cid, channel_context=system_in,
                      platform_tools=[t for t in (body.tools or []) if t.get("type") == "function"])
    events = request.app.state.agent.run(body.messages, ctx)

    if not body.stream:  # útil para la suite de regresión: devuelve además la traza del turno
        text, platform_calls, summary = "", [], None
        async for ev in events:
            if isinstance(ev, TextDelta):
                text += ev.text
            elif isinstance(ev, ToolCallsOut):
                platform_calls += ev.tool_calls
            elif isinstance(ev, TurnSummary):
                summary = ev
        message = {"role": "assistant", "content": text, **({"tool_calls": platform_calls} if platform_calls else {})}
        return {"id": f"chatcmpl-{cid}", "object": "chat.completion", "model": "opsvoice",
                "choices": [{"index": 0, "message": message,
                             "finish_reason": "tool_calls" if platform_calls else "stop"}],
                "opsvoice": summary.__dict__ if summary else None}

    async def sse():
        finish = "stop"
        yield _chunk(cid, {"role": "assistant"})
        async for ev in events:
            if isinstance(ev, TextDelta):
                yield _chunk(cid, {"content": ev.text})
            elif isinstance(ev, ToolCallsOut):
                finish = "tool_calls"
                calls = [{"index": i, **tc} for i, tc in enumerate(ev.tool_calls)]
                yield _chunk(cid, {"tool_calls": calls})
        yield _chunk(cid, {}, finish)
        yield "data: [DONE]\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ─────────────────────────────────── Visión ───────────────────────────────────


@app.post("/vision", dependencies=[Depends(require_api_key)])
async def vision(request: Request, referencia: str = Form(..., description="DNI / código de seguimiento / cuenta"),
                 archivo: UploadFile = File(...)):
    if archivo.content_type not in ("image/png", "image/jpeg", "image/webp"):
        raise HTTPException(415, "Formato no soportado: subí PNG, JPG o WEBP")
    content = await archivo.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(413, "La imagen supera los 5 MB")
    try:
        return await process_document(request.app.state.domain, referencia.strip().upper(), content,
                                      archivo.content_type)
    except VisionError as e:
        raise HTTPException(422, str(e)) from e


# ─────────────────────────────── Llamada saliente ───────────────────────────────


class OutboundCall(BaseModel):
    to_number: str
    dynamic_variables: dict = {}


@app.post("/calls/outbound", dependencies=[Depends(require_api_key)])
async def outbound_call(call: OutboundCall):
    """ElevenLabs llama por Twilio al número indicado con este agente (p. ej. campaña de mora)."""
    if not (settings.elevenlabs_api_key and settings.elevenlabs_agent_id and settings.elevenlabs_phone_number_id):
        raise HTTPException(500, "Faltan ELEVENLABS_API_KEY / ELEVENLABS_AGENT_ID / ELEVENLABS_PHONE_NUMBER_ID")
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://api.elevenlabs.io/v1/convai/twilio/outbound-call",
            headers={"xi-api-key": settings.elevenlabs_api_key},
            json={"agent_id": settings.elevenlabs_agent_id,
                  "agent_phone_number_id": settings.elevenlabs_phone_number_id,
                  "to_number": call.to_number,
                  "conversation_initiation_client_data": {"dynamic_variables": call.dynamic_variables}},
        )
    if resp.status_code >= 400:
        raise HTTPException(502, f"ElevenLabs respondió {resp.status_code}: {resp.text[:300]}")
    return resp.json()
