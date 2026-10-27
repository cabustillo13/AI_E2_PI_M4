# Setup de cuentas y credenciales

Todo va en `.env` (local) y en **Railway → servicio → Variables** (producción). Nunca en el repo.
El loop del agente es un loop de tools simple (M3 · clase 11): no hace falta LangGraph.

| # | Servicio | Qué crear | Variables | ¿Obligatorio? |
|---|---|---|---|---|
| 1 | - | Una clave propia para que ElevenLabs llame al backend: `python -c "import secrets; print(secrets.token_urlsafe(32))"` | `OPSVOICE_API_KEY` | Sí |
| 2 | OpenAI | API key (platform.openai.com → API keys) | `OPENAI_API_KEY` | Sí (modelo primario y visión) |
| 3 | Anthropic | API key (console.anthropic.com → API keys) | `ANTHROPIC_API_KEY` | No: solo si el fallback (`LLM_CHAIN`) usa otro proveedor |
| 4 | Langfuse Cloud | Proyecto → Settings → API keys (plan gratuito) | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | Sí (monitoreo online) |
| 5 | Railway | Proyecto conectado al repo de GitHub, un servicio para tu dominio | `DOMAIN` + las anteriores, `PUBLIC_URL`, `ELEVENLABS_AGENT_ID` | Sí |
| 6 | ElevenLabs | API key con permisos de Agents (Settings → API keys), plan gratuito | `ELEVENLABS_API_KEY` | Sí |
| 7 | GitHub | Secrets del repo para el gate de regresión en PRs | `OPENAI_API_KEY` | Recomendado |

Con un solo proveedor de LLM, el fallback es otro modelo del mismo proveedor:
`LLM_CHAIN=openai:gpt-4.1-mini,openai:gpt-4o-mini`.

## Orden

1. Completar 1, 2 y 4 en `.env` → `pytest -q`.
2. Railway: crear el servicio con tu `DOMAIN`, cargar las variables y generar el dominio público
   (*Settings → Networking → Generate domain*). Copiarlo en `PUBLIC_URL`. Comprobar `PUBLIC_URL/health`.
3. En el dashboard de ElevenLabs creá el agente: idioma, voz, primer mensaje y **LLM = Custom LLM** con
   URL `PUBLIC_URL/v1` y tu `OPSVOICE_API_KEY` como secret. Cargá la knowledge base del domain pack.
   En el system prompt de ElevenLabs incluí `conversation_id: {{system__conversation_id}}`.
4. Sobre ese agente:
   - **Guardrails**: activar los de contenido y prompt injection, y uno custom para datos de pago.
     Acotalo bien: un guardrail genérico de "datos sensibles" corta la conversación cuando el agente pide
     el DNI. Probalo con las simulaciones antes de darlo por bueno.
   - **Seguridad**: el agente tiene que ser público (sin autenticación) para el widget de `/demo`;
     agregá el dominio de Railway al *allowlist* para que solo funcione desde tu servicio.
   - **Duración máxima de la llamada** (Advanced → *Max conversation duration*): usá
     `duracion_max_llamada_s` del domain pack. La voz es ~85 % del costo y `/demo` es pública:
     el presupuesto del backend solo controla el LLM, este tope controla la voz.
   - Exportar la config (entregable): `python elevenlabs/export_agent.py <dominio> <agent_id>`.
5. Cargar el `agent_id` en `ELEVENLABS_AGENT_ID` (local y Railway) y abrir `PUBLIC_URL/demo`.
6. `python -m evals.run_simulations <dominio>` y, después de conversar por la demo,
   `python -m evals.online_report <dominio>`.

## Notas

- **La voz la paga la cuenta dueña del agente**, no la de la API key de Railway. Si cambiás de cuenta de
  ElevenLabs, el agente se crea de nuevo en esa cuenta y hay que cargar el `agent_id` nuevo en
  `ELEVENLABS_AGENT_ID` (`.env` y Railway).

- El widget de `/demo` usa el micrófono del navegador: hay que abrirla por HTTPS (Railway ya lo da) o en
  `localhost`.
- Langfuse: las organizaciones nuevas leen las trazas con la API v2 (`/api/public/v2/observations`).
