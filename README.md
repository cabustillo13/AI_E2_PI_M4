# OpsVoice — Agente de operaciones voice-first

Solución de referencia del **Proyecto Integrador M4 · AI Engineering 2.0 (Henry)**.
Un agente que atiende por **voz (web y teléfono)** una operación real del negocio, usa las herramientas
del negocio vía **MCP**, procesa un documento con **visión** y corre en **producción** con harness y evals.

Un solo código, tres dominios. El dominio se elige con una variable de entorno:

| `DOMAIN` | Empresa | Flujo principal (voz) | Documento (visión) |
|---|---|---|---|
| `clinica` | Clínica San Martín | Agendar, reprogramar y cancelar turnos | Orden médica |
| `logistica` | Rumbo Logística | Estado del envío y reprogramación de entregas fallidas | Remito |
| `cobranzas` | Delta Cobranzas | Informar deuda y acordar plan de pago (+ llamada saliente) | Factura |

---

## 1. Arquitectura

```
                 ┌──────────────────────── ElevenLabs Agents ────────────────────────┐
 📞 Teléfono ──► │ Twilio (nativo) ─┐                                                 │
 🌐 Widget web ─►│                  ├─► STT ─► turnos ─► TTS        guardrails,      │
                 │                  │          │  ▲                 KB, evaluación   │
                 └──────────────────┼──────────┼──┼─────────────────────────────────┘
                                    │  Custom LLM (OpenAI-compatible, SSE)
                                    ▼          ▼  │
 ┌──────────────────────────── Backend OpsVoice (FastAPI · Railway) ──────────────────────────┐
 │  POST /v1/chat/completions                                                                │
 │    guardrails (tarjetas/CBU fuera) → memoria de la conversación → presupuesto USD         │
 │    → LLM router (fallback OpenAI → Anthropic, modelo barato al 70 % del presupuesto)       │
 │    ⇄ loop de tools (máx. 5 vueltas) ⇄ cliente MCP ──stdio──► mcp_server (mocks del negocio)│
 │  POST /vision  → modelo de visión → Pydantic + reglas de negocio → relectura si falla     │
 │  POST /calls/outbound (cobranzas) · GET /metrics · GET /health · POST /admin/reset        │
 └──────────────┬─────────────────────────────────────────────────────────────────────────────┘
                └──► Langfuse (trazas por conversación, costo, latencia; PII enmascarada)
```

**Decisión central: el "cerebro" vive en el backend.** ElevenLabs se encarga de la voz (STT, TTS,
turnos, telefonía, guardrails de plataforma) y le delega el razonamiento a nuestro endpoint con su
opción **Custom LLM**. Gracias a eso:

- El harness (fallback, presupuesto, rate limit, tope de iteraciones) es **código propio y testeable**.
- La **suite de regresión** corre por texto contra el mismo endpoint, sin voz y sin costo de voz.
- El streaming **SSE** de la clase 1 es exactamente lo que ElevenLabs necesita para hablar mientras
  el modelo genera.

```
domains/          ← LO VARIABLE: un .md por dominio (frontmatter YAML + prompt + knowledge base)
  clinica.md · logistica.md · cobranzas.md · _comun.md (reglas compartidas)
src/              ← API FastAPI, agente, harness, proveedores LLM, observabilidad
mcp_server/       ← server MCP (FastMCP) + tools mock por dominio + store JSON
vision/           ← schemas Pydantic, extractor con verification loop, muestras sintéticas
elevenlabs/       ← scripts: crear/actualizar el agente, importar el número de Twilio, export JSON
evals/            ← regresión (texto), simulaciones (ElevenLabs), visión, monitoreo online
tests/            ← pytest sin claves (corre en CI en cada push)
docs/             ← resolución del experto, setup de cuentas
```

## 2. Setup

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                     # completar claves (ver docs/SETUP_CUENTAS.md)
pytest -q                                                # 41 tests, sin claves
uvicorn src.main:app --reload                            # http://localhost:8000/docs
```

Probar un turno por texto (lo mismo que manda ElevenLabs):

```bash
curl -s localhost:8000/v1/chat/completions -H "Authorization: Bearer $OPSVOICE_API_KEY" \
  -H "Content-Type: application/json" -H "X-Conversation-Id: demo-1" \
  -d '{"stream": false, "messages": [{"role": "user", "content": "Hola, quiero un turno con clínica médica"}]}'
```

Subir un documento al endpoint de visión:

```bash
curl -s localhost:8000/vision -H "Authorization: Bearer $OPSVOICE_API_KEY" \
  -F referencia=40123456 -F archivo=@vision/samples/clinica/orden_ok.png
```

### Deploy (Railway) y voz (ElevenLabs + Twilio)

1. Railway → *New project* → *Deploy from GitHub* → 3 servicios desde este repo, cada uno con su
   `DOMAIN` y las variables de `.env.example`. Activá *Wait for CI* para que solo despliegue si pasa CI.
   Rollback: *Deployments* → *Redeploy* sobre el deploy anterior.
2. `python elevenlabs/sync_agent.py clinica` → crea el agente (Custom LLM = `PUBLIC_URL/v1`) y guarda
   el export en `elevenlabs/agents/clinica.json`. Probalo desde el widget del dashboard.
3. `python elevenlabs/setup_phone.py clinica` → importa el número de Twilio y lo asigna al agente.
4. Cobranzas, llamada saliente: `POST /calls/outbound {"to_number": "+54911...", "dynamic_variables": {"cliente_nombre": "Roberto", "cuenta_id": "C-5001"}}`.

## 3. Decisiones técnicas

| Decisión | Por qué |
|---|---|
| **Domain pack en Markdown + frontmatter YAML** | El prompt y la KB son texto largo (más fácil de leer y editar en Markdown); la metadata (voz, presupuesto, criterios de evaluación) son datos con estructura (YAML). Un archivo = un dominio = una fuente de verdad para backend y ElevenLabs. |
| **Tools en Python, no en Markdown** | Las reglas de negocio (24 h para cancelar, cuotas según mora, DNI obligatorio) se validan en código: el prompt puede fallar, la tool no. |
| **MCP por stdio dentro del mismo contenedor** | Mismo patrón que M3 (FastMCP + ClientSession), sin un segundo deploy. |
| **Memoria de conversación en el backend** | ElevenLabs solo reenvía lo *hablado*: los resultados de tools (slot_id, turno_id) se perderían entre turnos. |
| **Fallback solo antes de hablar** | Si el modelo falla o tarda más de 6 s en la primera señal, se pasa al siguiente. Si ya empezó a hablar, no se puede "desdecir": se pide disculpas. |
| **Presupuesto por conversación** | 70 %: modelo barato. 100 %: mensaje de cierre fijo y `end_call`, sin gastar un token más. |
| **Guardrail de tarjetas/CBU antes del LLM** | "El LLM nunca toca datos de pago" se cumple aunque el prompt falle (Luhn + largo de CBU). |
| **Visión: structured output + reglas + 1 relectura** | Pydantic garantiza la forma; las reglas (CUIT, totales, vigencia, firma) detectan errores de contenido; la relectura dirigida corrige lecturas malas; si persiste → `requiere_revision`, nunca se "arregla" a mano. |
| **Un worker, estado en memoria** | Suficiente para el alcance. Escalar = mover memoria y presupuesto a Redis (mismo contrato). |
| **Modelos** | `gpt-4.1-mini` primario (baja latencia, sin razonamiento extendido: clave en voz); `claude-opus-5-5` (effort `low`) de respaldo; `gpt-4.1-nano` como modelo barato. Todo configurable por env. |

## 4. Evals de producción

| Capa | Qué mide | Cómo se corre | Cuándo |
|---|---|---|---|
| Tests unitarios/integración | Tools, harness, visión, API (LLM falso, MCP real) | `pytest -q` | Cada push (CI) |
| **Regresión pre-deploy** | 7–8 conversaciones guionadas por dominio: tools llamadas, políticas, inyecciones | `python -m evals.run_regression <dominio>` | Cada PR (CI, gate ≥ 85 %) |
| Visión | Status y exactitud por campo sobre 9 documentos (incluye inyección en la imagen) | `python -m evals.run_vision` | Al cambiar prompt/modelo de visión |
| **Simulaciones** | ≥ 10 conversaciones por dominio con usuario simulado (testing suite de ElevenLabs) | `python -m evals.run_simulations <dominio>` | Antes de la demo / defensa |
| Monitoreo online | Resolución, duración, TTFT p95, costo real, eventos del harness | `python -m evals.online_report <dominio>` + Langfuse | Continuo |

Resultados: `evals/reports/*.md` (se generan al correr cada suite con las claves configuradas).

## 5. Costo estimado cada 1.000 conversaciones

Supuestos: llamada de 3 min, ~8 turnos, ~1,6 llamadas al LLM por turno, ~2.500 tokens de entrada
por llamada (prompt + tools ≈ 1.600 fijos + historial) y ~60 de salida.

| Concepto | Cálculo | USD / 1.000 conv. |
|---|---|---|
| LLM (`gpt-4.1-mini`) | 13 llamadas × (2.500 × $0,40 + 60 × $1,60) / 1M | ≈ 14 |
| Voz ElevenLabs | 3 min × $0,10/min *(depende del plan)* | ≈ 300 |
| Telefonía Twilio | 3 min × $0,0085/min *(número de EE. UU., entrante)* | ≈ 26 |
| Visión (si 1 de cada 3 sube documento) | ~$0,002 por documento | ≈ 1 |
| **Total** | | **≈ 340** |

**Lectura:** la voz representa ~90 % del costo. Optimizar el LLM mueve poco; acortar las llamadas
(menos repreguntas, frases cortas) es la palanca real. El costo real medido sale de `evals.online_report`.
