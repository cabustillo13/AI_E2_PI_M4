# Setup de cuentas y credenciales

Todo va en `.env` (local) y en **Railway → servicio → Variables** (producción). Nunca en el repo.
El loop del agente es un loop de tools simple (M3 · clase 11): no hace falta LangGraph.

| # | Servicio | Qué crear | Variables | ¿Obligatorio? |
|---|---|---|---|---|
| 1 | — | Una clave propia para que ElevenLabs llame al backend: `python -c "import secrets; print(secrets.token_urlsafe(32))"` | `OPSVOICE_API_KEY` | Sí |
| 2 | OpenAI | API key (platform.openai.com → API keys) | `OPENAI_API_KEY` | Sí (modelo primario y visión) |
| 3 | Anthropic | API key (console.anthropic.com → API keys) | `ANTHROPIC_API_KEY` | No: solo si el fallback (`LLM_CHAIN`) usa otro proveedor |
| 4 | Langfuse Cloud | Proyecto → Settings → API keys (plan gratuito) | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | Sí (monitoreo online) |
| 5 | Railway | Proyecto conectado al repo de GitHub, un servicio por dominio | `DOMAIN` + las anteriores, `PUBLIC_URL`, `ELEVENLABS_AGENT_ID` | Sí |
| 6 | ElevenLabs | API key con permisos de Agents (Settings → API keys), plan gratuito | `ELEVENLABS_API_KEY` | Sí |
| 7 | GitHub | Secrets del repo para el gate de regresión en PRs | `OPENAI_API_KEY` | Recomendado |

Con un solo proveedor de LLM, el fallback es otro modelo del mismo proveedor:
`LLM_CHAIN=openai:gpt-4.1-mini,openai:gpt-4o-mini` y `VISION_FALLBACK=openai:gpt-4o-mini`.

## Orden

1. Completar 1, 2 y 4 en `.env` → `pytest -q` y `python -m evals.run_regression clinica` en local.
2. Railway: crear el servicio (`DOMAIN=clinica|logistica|cobranzas`), cargar las variables y generar el
   dominio público (*Settings → Networking → Generate domain*). Copiarlo en `PUBLIC_URL` (local y Railway).
   Comprobar: `PUBLIC_URL/health` responde `{"status":"ok", ...}`.
3. `python elevenlabs/sync_agent.py <dominio>` → crea el agente con Custom LLM, KB, guardrails, evaluación
   post-llamada y acceso restringido a `PUBLIC_URL`. El export queda en `elevenlabs/agents/<dominio>.json`.
4. Copiar el `agent_id` del export en `ELEVENLABS_AGENT_ID` (local y Railway) y abrir `PUBLIC_URL/demo`.
5. `python -m evals.run_simulations <dominio>` y, después de conversar por la demo,
   `python -m evals.online_report <dominio>`.

## Notas

- Si agregás guardrails custom en ElevenLabs, acotalos: uno genérico de "datos sensibles" corta la
  conversación cuando el agente pide el DNI. Probalos con las simulaciones antes de darlos por buenos.
- El widget de `/demo` usa el micrófono del navegador: hay que abrirla por HTTPS (Railway ya lo da) o en
  `localhost`.
- Langfuse: las organizaciones nuevas leen las trazas con la API v2 (`/api/public/v2/observations`).
