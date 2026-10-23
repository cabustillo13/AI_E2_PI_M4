"""Rumbo Logística — mock del sistema de tracking.

Reglas de negocio que viven en las tools:
- Sin DNI del destinatario correcto no se informa nada del envío.
- Solo se reprograma una entrega fallida, máximo 2 veces, en franjas de los próximos 3 días hábiles.
"""

from __future__ import annotations

from datetime import date, timedelta

from mcp_server import store

DOMAIN = "logistica"
FRANJAS = {"manana": "9 a 13 h", "tarde": "14 a 18 h"}
MAX_REPROGRAMACIONES = 2


def _dias_habiles(desde: date, cantidad: int) -> list[date]:
    dias, d = [], desde
    while len(dias) < cantidad:
        d += timedelta(days=1)
        if d.weekday() < 6:  # lunes a sábado
            dias.append(d)
    return dias


def seed() -> dict:
    hoy = store.today()
    ayer, manana = (hoy - timedelta(days=1)).isoformat(), _dias_habiles(hoy, 1)[0].isoformat()
    return {
        "envios": {
            "RL-100234": {
                "destinatario": "Carlos Díaz", "dni": "33444555", "localidad": "CABA",
                "direccion": "Av. Corrientes 3200, 4° B", "estado": "en_transito", "eta": manana,
                "reprogramaciones": 0, "historial": [f"{ayer}: ingresó al centro de distribución"],
            },
            "RL-100235": {
                "destinatario": "Ana Torres", "dni": "29888777", "localidad": "Lanús",
                "direccion": "Hipólito Yrigoyen 4500", "estado": "entrega_fallida", "eta": None,
                "motivo_falla": "destinatario ausente", "reprogramaciones": 0,
                "historial": [f"{ayer}: intento de entrega fallido (destinatario ausente)"],
            },
            "RL-100238": {
                "destinatario": "Jorge Paz", "dni": "30555666", "localidad": "Quilmes",
                "direccion": "Rivadavia 300", "estado": "entrega_fallida", "eta": None,
                "motivo_falla": "domicilio cerrado", "reprogramaciones": 1,
                "historial": [f"{ayer}: intento de entrega fallido (domicilio cerrado)"],
            },
            "RL-100236": {
                "destinatario": "Diego Romero", "dni": "31222333", "localidad": "CABA",
                "direccion": "Gorriti 5800", "estado": "entregado", "eta": None, "reprogramaciones": 0,
                "historial": [f"{ayer}: entregado"],
            },
            "RL-100237": {
                "destinatario": "Paula Ríos", "dni": "36555444", "localidad": "Avellaneda",
                "direccion": "Mitre 750", "estado": "en_sucursal", "eta": None, "reprogramaciones": 2,
                "historial": [f"{ayer}: segundo intento fallido, enviado a sucursal central"],
            },
        },
        # Remitos procesados por /vision (clave = código de seguimiento).
        "documentos": {
            "RL-100236": {
                "status": "valido",
                "data": {
                    "numero_remito": "R-0003-00045871", "fecha": ayer, "codigo_seguimiento": "RL-100236",
                    "receptor_nombre": "Marta Romero", "receptor_dni": "14555666", "bultos": 1,
                    "firma_presente": True, "observaciones": "Recibió familiar",
                },
            }
        },
    }


def _data() -> dict:
    return store.load(DOMAIN, seed)


def _codigo(codigo: str) -> str:
    """'RL100234', 'rl-100234', 'R L 100234' → 'RL-100234'."""
    return f"RL-{store.solo_digitos(codigo)}"


def _verificar(envio: dict | None, dni: str) -> str | None:
    if not envio or envio["dni"] != store.solo_digitos(dni):
        return "No encontramos un envío con ese código y DNI."
    return None


# ─────────────────────────────── Tools ───────────────────────────────


def consultar_envio(codigo_seguimiento: str, dni_destinatario: str) -> dict:
    """Estado de un envío. Requiere código (RL-XXXXXX) y DNI del destinatario."""
    codigo = _codigo(codigo_seguimiento)
    envio = _data()["envios"].get(codigo)
    if error := _verificar(envio, dni_destinatario):
        return {"ok": False, "error": error}
    resp = {k: envio[k] for k in ("destinatario", "estado", "eta", "localidad", "reprogramaciones", "historial")}
    if envio["eta"]:
        resp["eta_legible"] = store.fecha_legible(envio["eta"])
    if envio["estado"] == "entrega_fallida":
        resp["motivo_falla"] = envio["motivo_falla"]
    if envio["estado"] == "en_sucursal":
        resp["sucursal"] = "Av. Warnes 2100, CABA (lunes a viernes 9 a 19 h, sábados 9 a 13 h)"
    return {"ok": True, "codigo_seguimiento": codigo, **resp}


def opciones_reprogramacion(codigo_seguimiento: str) -> dict:
    """Fechas y franjas disponibles para reprogramar una entrega fallida (próximos 3 días hábiles)."""
    envio = _data()["envios"].get(_codigo(codigo_seguimiento))
    if not envio:
        return {"ok": False, "error": "Envío inexistente."}
    if envio["estado"] != "entrega_fallida":
        return {"ok": False, "error": f"Solo se reprograman entregas fallidas (estado actual: {envio['estado']})."}
    if envio["reprogramaciones"] >= MAX_REPROGRAMACIONES:
        return {"ok": False, "error": "Se alcanzó el máximo de reprogramaciones: ofrecer retiro en sucursal."}
    opciones = [{"fecha": d.isoformat(), "dia": store.fecha_legible(d.isoformat()), "franja": f, "horario": h}
                for d in _dias_habiles(store.today(), 3) for f, h in FRANJAS.items()]
    return {"ok": True, "opciones": opciones}


def reprogramar_entrega(codigo_seguimiento: str, fecha: str, franja: str, nueva_direccion: str | None = None) -> dict:
    """Reprograma una entrega fallida. franja: 'manana' | 'tarde'. nueva_direccion opcional (misma localidad)."""
    envio = _data()["envios"].get(_codigo(codigo_seguimiento))
    if envio and envio["estado"] == "reprogramado" and envio["eta"] == fecha and envio.get("franja") == franja:
        # idempotente: repetir la misma reprogramación (p. ej. tras una interrupción) no la duplica
        return {"ok": True, "ya_estaba_reprogramado": True, "fecha": fecha, "dia": store.fecha_legible(fecha),
                "franja": franja, "horario": FRANJAS[franja], "direccion": envio["direccion"]}
    opciones = opciones_reprogramacion(codigo_seguimiento)
    if not opciones["ok"]:
        return opciones
    if {"fecha": fecha, "franja": franja} not in [{"fecha": o["fecha"], "franja": o["franja"]} for o in opciones["opciones"]]:
        return {"ok": False, "error": "Fecha o franja fuera de las opciones disponibles."}
    with store.edit(DOMAIN, seed) as data:
        envio = data["envios"][_codigo(codigo_seguimiento)]
        envio.update(estado="reprogramado", eta=fecha, franja=franja)
        envio["reprogramaciones"] += 1
        if nueva_direccion:
            envio["direccion"] = nueva_direccion
        envio["historial"].append(f"{store.today().isoformat()}: reprogramado para {fecha} ({FRANJAS[franja]})")
        return {"ok": True, "fecha": fecha, "dia": store.fecha_legible(fecha), "franja": franja, "horario": FRANJAS[franja],
                "direccion": envio["direccion"]}


def consultar_remito(codigo_seguimiento: str, dni_destinatario: str) -> dict:
    """Remito firmado de un envío entregado (subido por el repartidor y procesado con visión).
    Requiere el DNI del destinatario, igual que consultar_envio."""
    data = _data()
    if error := _verificar(data["envios"].get(_codigo(codigo_seguimiento)), dni_destinatario):
        return {"ok": False, "error": error}
    doc = data["documentos"].get(_codigo(codigo_seguimiento))
    if not doc:
        return {"ok": False, "error": "No hay remito cargado para este envío."}
    d = doc["data"]
    # Nunca se expone el DNI completo del receptor: solo los últimos 3 dígitos.
    return {"ok": True, "status": doc["status"], "fecha": d.get("fecha"), "receptor_nombre": d.get("receptor_nombre"),
            "receptor_dni_final": (d.get("receptor_dni") or "")[-3:], "firma_presente": d.get("firma_presente"),
            "observaciones": d.get("observaciones")}


TOOLS = [consultar_envio, opciones_reprogramacion, reprogramar_entrega, consultar_remito]
