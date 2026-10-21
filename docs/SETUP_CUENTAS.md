# Setup de cuentas y credenciales

Todo va en `.env` (local) y en **Railway → servicio → Variables** (producción). Nunca en el repo.
No hace falta LangGraph: el loop del agente es un loop de tools simple (M3 · clase 11).

| # | Servicio | Qué crear | Variables | ¿Obligatorio? |
|---|---|---|---|---|
| 1 | — | Una clave propia para que ElevenLabs llame al backend: `python -c "import secrets; print(secrets.token_urlsafe(32))"` | `OPSVOICE_API_KEY` | Sí |
| 2 | OpenAI | API key (platform.openai.com → API keys) | `OPENAI_API_KEY` | Sí (modelo primario y visión) |
| 3 | Anthropic | API key (console.anthropic.com → API keys) | `ANTHROPIC_API_KEY` | Sí para demostrar el fallback entre proveedores |
| 4 | Langfuse Cloud | Proyecto → Settings → API keys (plan gratuito) | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | Sí (monitoreo online) |
| 5 | Railway | Proyecto conectado al repo de GitHub, un servicio por dominio | `DOMAIN` + todas las anteriores; después `PUBLIC_URL` | Sí |
| 6 | ElevenLabs | API key con permisos de Agents (Settings → API keys) | `ELEVENLABS_API_KEY` | Sí |
| 7 | Twilio | Cuenta + número con voz (Phone Numbers → Buy a number) | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` | Sí para el canal telefónico |
| 8 | GitHub | Secrets del repo para el gate de regresión en PRs | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | Recomendado |

## Orden sugerido

1. Completar 1–4 en `.env` → `pytest -q` y `python -m evals.run_regression clinica` en local.
2. Railway: crear los 3 servicios (`DOMAIN=clinica|logistica|cobranzas`), cargar variables, generar dominio
   público (*Settings → Networking → Generate domain*) y copiarlo en `PUBLIC_URL`.
3. `python elevenlabs/sync_agent.py <dominio>` (con el `PUBLIC_URL` de ese servicio).
4. En el dashboard de ElevenLabs, sobre el agente creado:
   - **Security → Guardrails**: activar los de contenido y prompt injection, y agregar un guardrail
     custom: *"El agente nunca pide ni repite números de tarjeta, CBU, claves o códigos de seguridad."*
   - Probar con el widget web (botón *Test AI agent*).
   - Volver a exportar: `python elevenlabs/sync_agent.py <dominio> --export`.
5. `python elevenlabs/setup_phone.py <dominio>` → copiar `ELEVENLABS_PHONE_NUMBER_ID` y el
   `ELEVENLABS_AGENT_ID` del export en las variables del servicio de Railway (cobranzas los usa para llamar).
6. `python -m evals.run_simulations <dominio>` y `python -m evals.online_report <dominio>`.

## Notas sobre Twilio (importante para la defensa)

- Con cuenta **trial** solo se puede llamar a/desde **números verificados** y Twilio reproduce un aviso
  antes de cada llamada. Para la defensa conviene cargar saldo (USD 20 alcanza) y comprar un número de
  EE. UU. (~USD 1,15/mes): los números argentinos exigen documentación regulatoria.
- Llamar desde Argentina a un número de EE. UU. tiene costo para quien llama. Alternativa: **llamada
  saliente** (`POST /calls/outbound`) al celular de la persona que evalúa.
- Plan B si la telefonía falla en vivo: widget web de ElevenLabs + video del canal telefónico grabado.
