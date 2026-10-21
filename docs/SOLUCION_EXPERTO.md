# 9. Resolución del caso — entrega del experto

**Proyecto:** OpsVoice — Agente de operaciones voice-first · **Módulo:** M4 · Producción y Multimodal
**Experto desarrollador:** Carlos B. · **Alcance:** solución de referencia completa para los 3 dominios del menú.

## 9.1 Qué se entrega

| Pieza | Dónde | Para quién |
|---|---|---|
| **Scaffold oficial** (lo que recibe el estudiante) | rama `scaffold` | Estudiantes |
| **Solución de referencia** (3 dominios) | rama `main` | Equipo docente / TAs |
| Domain packs (prompt + KB + metadata) | `domains/*.md` | Ambos |
| Mocks de negocio vía MCP | `mcp_server/` (incluidos en el scaffold, como pide la consigna) | Ambos |
| Documentos de muestra para visión | `vision/samples/` (incluidos en el scaffold) | Ambos |
| Evals de producción (regresión, visión, simulaciones, online) | `evals/` | Ambos (el scaffold trae el formato y 1 caso de ejemplo) |
| Setup de cuentas y costos | `docs/SETUP_CUENTAS.md` | Ambos |

**Qué trae el scaffold y qué construye el estudiante**

| Ya viene (plumbing) | Lo construye el estudiante (lo que enseña el módulo) |
|---|---|
| Estructura del repo, Dockerfile, docker-compose, `railway.json`, CI | Endpoint `/v1/chat/completions` con SSE y auth (C16) |
| Server MCP con las tools mock de los 3 dominios + store | Deploy y variables en Railway (C17) |
| Domain packs con datos del negocio (persona, políticas, KB) | Harness: fallback, presupuesto, rate limit, guardrails (C18) |
| Cliente MCP (`src/mcp_client.py`) y carga del domain pack | Schemas de visión + reglas + verification loop (C19) |
| Imágenes de muestra y su golden set | Configuración del agente ElevenLabs + Twilio (C20) |
| Runners de evals (formato YAML) | Casos de regresión, escenarios de simulación y reporte (C21) |

## 9.2 Decisiones técnicas clave (y por qué)

1. **Scaffold FastAPI + Docker + GitHub Actions + Railway.** Un Dockerfile, un `railway.json` con
   healthcheck y un CI con tres jobs: tests sin claves (cada push), build + smoke del contenedor, y
   regresión con LLM real como gate en PRs. Railway despliega desde `main` con *Wait for CI*; el rollback
   es redeploy del deploy anterior. Guía alternativa AWS: la misma imagen corre en App Runner/ECS sin cambios.
2. **El cerebro en el backend (ElevenLabs Custom LLM).** Es la decisión que hace coherente el módulo:
   sin ella, el harness de C18 y la regresión de C21 quedarían como configuración de la plataforma.
   ElevenLabs aporta voz, turnos, telefonía, KB y guardrails de plataforma; el backend razona, llama tools
   y aplica el harness. El SSE de C16 es el contrato que ElevenLabs exige.
3. **Tools de negocio como server MCP mock** (FastMCP, stdio, mismo contenedor). Las reglas de negocio viven
   en las tools y devuelven errores recuperables (`{"ok": false, "error": ...}`) que el LLM explica.
4. **Un código, tres dominios por configuración.** `DOMAIN=clinica|logistica|cobranzas` elige el domain pack
   (`domains/<id>.md`) y el módulo de tools. Markdown para el texto largo (prompt, KB), frontmatter YAML para
   los datos (voz, presupuesto, criterios de evaluación). Las tools y los schemas quedan en Python: son
   reglas que hay que testear, no texto.
5. **Visión con salida estructurada validada.** Structured outputs con el schema Pydantic → reglas de
   negocio (CUIT, sumas, vigencia, firma, coincidencia con la referencia) → una relectura dirigida si hay
   errores (verification loop) → `valido` o `requiere_revision`. El resultado se guarda y el agente lo
   consulta durante la llamada con una tool (`consultar_orden_medica`, `consultar_remito`, `consultar_factura`).
6. **Telefonía con la integración nativa ElevenLabs + Twilio** (import del número por API o dashboard).
   Cobranzas suma la llamada saliente con un único endpoint.
7. **Monitoreo con Langfuse** (sesión = `conversation_id`, generación por llamada al LLM con costo, span por
   tool, PII enmascarada) + `/metrics` (TTFT p50/p95, costo por conversación, eventos del harness) +
   evaluación post-llamada de ElevenLabs (criterios definidos en el frontmatter).
8. **Simulación con la testing suite de la plataforma** (tests de tipo *simulation*: escenario + condiciones
   de éxito), ≥ 10 por dominio, creados y corridos por API.

## 9.3 Diagnóstico de la propuesta (ajustes recomendados al documento del módulo)

| # | Hallazgo | Ajuste aplicado en la solución | Sugerencia para la consigna |
|---|---|---|---|
| 1 | No se define dónde razona el agente. Si lo hace el LLM nativo de ElevenLabs, el harness no es código propio. | Custom LLM → backend. | Explicitarlo en §3: "el agente de ElevenLabs usa como LLM el backend propio". |
| 2 | Visión en un canal de voz: por teléfono no se puede mandar una foto. | `POST /vision` + tool MCP que consulta el documento procesado. | Explicitar el flujo "se sube por web → se usa en la llamada". |
| 3 | El scaffold "provisto por Henry" no existía. | Rama `scaffold` derivada de esta solución. | Indicar quién lo mantiene y la fecha de entrega en el gantt. |
| 4 | Cobranzas pide "contactar" (llamada saliente): más trabajo que los otros dominios. | Un endpoint `/calls/outbound`. | Marcar la llamada saliente como requisito solo de cobranzas o como extra credit para equilibrar. |
| 5 | "Suite de regresión" no está definida. | Regresión por texto contra el mismo endpoint, gate en CI. | Definirla en §4 (formato + umbral). |
| 6 | La voz llega en C20 (anteúltima clase). | El flujo se valida por texto desde la semana 1. | Recomendar en §5 "validar el flujo por texto antes de C20". |
| 7 | Costos y logística de telefonía (trial de Twilio, números AR, créditos de ElevenLabs/Railway). | `docs/SETUP_CUENTAS.md` + plan B de defensa. | Prever créditos por estudiante o un número compartido por cohorte. |
| 8 | MCP no figura en el temario de M4 (viene de M3 · C14). | Se reutiliza la misma API (mcp 1.x). | Mencionarlo como prerrequisito en la recorrida del scaffold (C16). |

## 9.4 Mapa clase → código de la solución

| Clase | Tema | Archivos de referencia |
|---|---|---|
| C16 | API, SSE, auth, errores HTTP | `src/main.py` |
| C17 | Docker, secretos, deploy, CI/CD, rollback | `Dockerfile`, `railway.json`, `.github/workflows/ci.yml`, `.env.example` |
| C18 | Harness | `src/harness/` (router, budget, rate_limit, guardrails), `src/agent.py` (tope de iteraciones) |
| C19 | Visión | `vision/schemas.py`, `vision/extractor.py`, `vision/samples/` |
| C20 | Voz y telefonía | `elevenlabs/sync_agent.py`, `elevenlabs/setup_phone.py`, `domains/*.md` |
| C21 | Evals de producción | `evals/` (regression, simulations, vision, online_report), `src/observability.py` |

## 9.5 Guía para la corrección y la defensa 1:1

**Lo que tiene que poder mostrar el estudiante en vivo**

1. Llamada telefónica real resolviendo el flujo principal (o saliente, en cobranzas).
2. La traza de esa llamada en Langfuse: turnos, tools llamadas, costo y latencia.
3. Una demo del harness: forzar la caída del modelo primario (por ejemplo
   `LLM_CHAIN=openai:modelo-inexistente,anthropic:claude-opus-5-5`) y ver el fallback en `/metrics` y en
   Langfuse; bajar `presupuesto_usd_conversacion` y ver la degradación al modelo barato y el cierre.
4. Un documento procesado con visión que el agente usa en la llamada.
5. Los reportes de evals (regresión ≥ 85 %, ≥ 10 simulaciones, visión) y el costo cada 1.000 conversaciones.

**Preguntas de defensa sugeridas**

- ¿Por qué el fallback no puede ocurrir después de que el agente empezó a hablar?
- ¿Por qué la verificación de identidad está en la tool y no solo en el prompt?
- ¿Qué pasa con la memoria de la conversación si escalás a 3 réplicas? ¿Cómo lo resolverías?
- ¿Por qué medir latencia p95 y no el promedio en voz?
- En tu costo por 1.000 conversaciones, ¿qué componente domina y cómo lo bajarías?
- Mostrame un caso de regresión que falló y qué cambiaste para que pase.

**Señales de nivel Excelente:** harness demostrable en vivo, evals con fallas analizadas (no solo
el porcentaje), costos medidos y no solo estimados, decisiones justificadas con datos.

## 9.6 Plan B de producción (dominio único)

Si los assets de los tres dominios no llegan a tiempo, se usa solo `clinica` (el más completo y con el
flujo de visión más claro). No cambia código: se entrega el scaffold con un solo domain pack y un solo
módulo de tools.

## 9.7 Lo que esta solución deja fuera a propósito

WhatsApp (bonus), escalación a humano con resumen (extra credit; el prompt ya ofrece derivar),
segundo idioma (extra credit: alcanza con otro domain pack y `idioma: en`), dashboard propio
(se cubre con Langfuse + `evals/online_report.py`), LangGraph (no aporta para un loop de tools simple).
