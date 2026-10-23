"""Demo pública (GET /demo): una página con el widget de voz de ElevenLabs para hablar con el agente.

Es el canal de voz del sistema completo: voz del navegador → ElevenLabs → este backend
→ tools MCP. La página muestra los datos ficticios del domain pack (`datos_demo`) para que cualquiera
pueda probar el flujo principal, y en cobranzas permite simular una campaña (`campana_demo`).
"""

from __future__ import annotations

import json
from html import escape

from src.domain import Domain

WIDGET_SCRIPT = "https://unpkg.com/@elevenlabs/convai-widget-embed"

PAGE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{empresa} · Demo de voz</title>
<style>
  :root {{ --bg: #f7f7f5; --card: #ffffff; --text: #1d1d1b; --muted: #5f5f5a; --line: #e4e4df; --accent: #2457d6; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #141413; --card: #1f1f1d; --text: #ececea; --muted: #a3a39e; --line: #33332f; --accent: #7aa2ff; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--text); font: 16px/1.55 system-ui, sans-serif; }}
  main {{ max-width: 720px; margin: 0 auto; padding: 40px 16px 120px; }}
  h1 {{ font-size: 1.6rem; margin: 0 0 4px; }}
  .sub {{ color: var(--muted); margin: 0 0 28px; }}
  section {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 18px 20px; margin-bottom: 16px; }}
  h2 {{ font-size: 1rem; margin: 0 0 10px; }}
  ul {{ margin: 0; padding-left: 20px; }}
  li {{ margin: 4px 0; }}
  a {{ color: var(--accent); }}
  .modo {{ display: flex; gap: 12px; flex-wrap: wrap; }}
  .modo a {{ padding: 6px 12px; border: 1px solid var(--line); border-radius: 999px; text-decoration: none; }}
  .modo a.activo {{ border-color: var(--accent); font-weight: 600; }}
</style>
</head>
<body>
<main>
  <h1>{empresa}</h1>
  <p class="sub">Hablá con {agente}, el agente de voz. Tocá el botón de la esquina inferior derecha y permití el micrófono.</p>
  {modo}
  <section>
    <h2>Qué podés pedirle</h2>
    <p>{flujo}</p>
  </section>
  <section>
    <h2>Datos de prueba (ficticios)</h2>
    <ul>{datos}</ul>
  </section>
</main>
<elevenlabs-convai agent-id="{agent_id}" dynamic-variables='{variables}'></elevenlabs-convai>
<script src="{script}" async type="text/javascript"></script>
</body>
</html>
"""


def render(domain: Domain, agent_id: str, campana: bool) -> str:
    meta = domain.meta
    variables = dict(meta.get("variables_dinamicas") or {})
    modo = ""
    if meta.get("campana_demo"):
        if campana:
            variables.update(meta["campana_demo"])
        modo = ('<p class="modo"><a href="?" class="{0}">El cliente inicia el contacto</a>'
                '<a href="?campana=1" class="{1}">Campaña: el agente contacta a {2}</a></p>').format(
            "" if campana else "activo", "activo" if campana else "", escape(meta["campana_demo"]["cliente_nombre"]))
    return PAGE.format(
        empresa=escape(meta["empresa"]),
        agente=escape(meta["agente"]),
        modo=modo,
        flujo=escape(meta.get("resumen", "")),
        datos="".join(f"<li>{escape(d)}</li>" for d in meta.get("datos_demo") or []),
        agent_id=escape(agent_id),
        variables=escape(json.dumps(variables, ensure_ascii=False), quote=True),
        script=WIDGET_SCRIPT,
    )
