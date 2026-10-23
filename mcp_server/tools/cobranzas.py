"""Delta Cobranzas — mock del sistema de cuentas en mora.

Reglas de negocio que viven en las tools:
- Planes: mora <=30 días → hasta 3 cuotas sin interés; 31-60 → hasta 6 cuotas con 5 % de recargo;
  >60 → sin plan (derivar). Cuota mínima $10.000. Primer pago dentro de 7 días.
- El pago SIEMPRE es por link: ninguna tool recibe datos de tarjeta.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from mcp_server import store

DOMAIN = "cobranzas"
CUOTA_MINIMA = 10_000
LINK_BASE = "https://pagos.deltacobranzas.example/p/"


def seed() -> dict:
    return {
        "deudores": {
            "27333444": {"nombre": "Roberto Sánchez", "fecha_nacimiento": "1980-03-15",
                         "telefono": "+5491155550001", "email": "roberto@example.com", "cuentas": ["C-5001"]},
            "35666777": {"nombre": "Laura Gómez", "fecha_nacimiento": "1991-09-30",
                         "telefono": "+5491155550002", "email": "laura@example.com", "cuentas": ["C-5002"]},
            "22111000": {"nombre": "Héctor Molina", "fecha_nacimiento": "1972-01-08",
                         "telefono": "+5491155550003", "email": "hector@example.com", "cuentas": ["C-5003"]},
            "33999111": {"nombre": "Marcos Vidal", "fecha_nacimiento": "1988-06-20",
                         "telefono": "+5491155550004", "email": "marcos@example.com", "cuentas": ["C-5004"]},
        },
        "cuentas": {
            "C-5001": {"servicio": "Internet Fibra 300 MB", "deuda": 45_800.0, "dias_mora": 18,
                       "facturas_vencidas": [{"numero": "B-0004-00081234", "periodo": "octubre", "importe": 45_800.0}]},
            "C-5002": {"servicio": "Internet Fibra 1 GB", "deuda": 128_500.0, "dias_mora": 41,
                       "facturas_vencidas": [{"numero": "B-0004-00079012", "periodo": "septiembre", "importe": 64_250.0},
                                             {"numero": "B-0004-00081235", "periodo": "octubre", "importe": 64_250.0}]},
            "C-5003": {"servicio": "Internet 100 MB", "deuda": 96_000.0, "dias_mora": 75,
                       "facturas_vencidas": [{"numero": "B-0004-00071111", "periodo": "agosto", "importe": 32_000.0}]},
            "C-5004": {"servicio": "Internet Fibra 500 MB", "deuda": 38_000.0, "dias_mora": 10,
                       "facturas_vencidas": [{"numero": "B-0004-00081240", "periodo": "octubre", "importe": 38_000.0}]},
        },
        "acuerdos": {},
        "envios_link": [],
        # Facturas subidas por el cliente por /vision (clave = cuenta_id).
        "documentos": {},
        "proximo_acuerdo": 1,
    }


def _data() -> dict:
    return store.load(DOMAIN, seed)


def _regla(dias_mora: int) -> dict | None:
    if dias_mora <= 30:
        return {"max_cuotas": 3, "recargo": 0.0}
    if dias_mora <= 60:
        return {"max_cuotas": 6, "recargo": 0.05}
    return None


# ─────────────────────────────── Tools ───────────────────────────────


def verificar_deudor(dni: str, fecha_nacimiento: str) -> dict:
    """Verifica la identidad del titular con DNI y fecha de nacimiento (YYYY-MM-DD).
    Llamar SIEMPRE antes de mencionar cualquier dato de la deuda."""
    deudor = _data()["deudores"].get(store.solo_digitos(dni))
    if not deudor or deudor["fecha_nacimiento"] != fecha_nacimiento.strip():
        return {"ok": False, "error": "Los datos no coinciden con ningún titular."}
    return {"ok": True, "titular": {"dni": dni, "nombre": deudor["nombre"], "cuentas": deudor["cuentas"]}}


def consultar_deuda(dni: str) -> dict:
    """Deuda vigente del titular verificado: cuentas, montos y días de mora."""
    data = _data()
    deudor = data["deudores"].get(store.solo_digitos(dni))
    if not deudor:
        return {"ok": False, "error": "Titular inexistente."}
    cuentas = [{"cuenta_id": cid, **data["cuentas"][cid]} for cid in deudor["cuentas"]]
    return {"ok": True, "cuentas": cuentas}


def simular_plan(cuenta_id: str, cuotas: int) -> dict:
    """Simula un plan de pago en N cuotas según la política de mora. No registra nada."""
    cuenta = _data()["cuentas"].get(cuenta_id)
    if not cuenta:
        return {"ok": False, "error": "Cuenta inexistente."}
    regla = _regla(cuenta["dias_mora"])
    if regla is None:
        return {"ok": False, "error": "Mora mayor a 60 días: no se ofrece plan, derivar a un operador."}
    if not 1 <= cuotas <= regla["max_cuotas"]:
        return {"ok": False, "error": f"Para esta cuenta se permiten de 1 a {regla['max_cuotas']} cuotas."}
    total = round(cuenta["deuda"] * (1 + regla["recargo"]), 2)
    monto_cuota = math.ceil(total / cuotas * 100) / 100
    if cuotas > 1 and monto_cuota < CUOTA_MINIMA:
        return {"ok": False, "error": f"La cuota quedaría por debajo del mínimo de ${CUOTA_MINIMA:,}. Probar con menos cuotas."}
    return {"ok": True, "cuenta_id": cuenta_id, "cuotas": cuotas, "monto_cuota": monto_cuota,
            "total": total, "recargo_porcentaje": regla["recargo"] * 100, "max_cuotas": regla["max_cuotas"]}


def registrar_acuerdo(cuenta_id: str, cuotas: int, fecha_primer_pago: str) -> dict:
    """Registra el plan acordado (fecha_primer_pago YYYY-MM-DD, dentro de 7 días) y devuelve el link de pago."""
    plan = simular_plan(cuenta_id, cuotas)
    if not plan["ok"]:
        return plan
    try:
        fecha = date.fromisoformat(fecha_primer_pago)
    except ValueError:
        return {"ok": False, "error": "Fecha inválida, usar YYYY-MM-DD."}
    if not store.today() <= fecha <= store.today() + timedelta(days=7):
        return {"ok": False, "error": "El primer pago debe ser dentro de los próximos 7 días."}
    with store.edit(DOMAIN, seed) as data:
        previo = next(((aid, a) for aid, a in data["acuerdos"].items() if a["cuenta_id"] == cuenta_id), None)
        if previo:
            aid, a = previo
            if a["cuotas"] == cuotas and a["fecha_primer_pago"] == fecha_primer_pago:  # idempotente
                return {"ok": True, "acuerdo_id": aid, "ya_estaba_registrado": True, **a}
            return {"ok": False, "error": "La cuenta ya tiene un acuerdo vigente."}
        acuerdo_id = f"A-{data['proximo_acuerdo']:04d}"
        data["proximo_acuerdo"] += 1
        acuerdo = {"cuenta_id": cuenta_id, "cuotas": cuotas, "monto_cuota": plan["monto_cuota"],
                   "total": plan["total"], "fecha_primer_pago": fecha_primer_pago,
                   "link_pago": f"{LINK_BASE}{acuerdo_id}"}
        data["acuerdos"][acuerdo_id] = acuerdo
        return {"ok": True, "acuerdo_id": acuerdo_id, **acuerdo}


def enviar_link_pago(cuenta_id: str, canal: str) -> dict:
    """Envía el link de pago del acuerdo de la cuenta. canal: 'sms' | 'email' (mock: no envía nada real)."""
    if canal not in ("sms", "email"):
        return {"ok": False, "error": "Canal inválido: usar 'sms' o 'email'."}
    with store.edit(DOMAIN, seed) as data:
        acuerdo = next((a for a in data["acuerdos"].values() if a["cuenta_id"] == cuenta_id), None)
        if not acuerdo:
            return {"ok": False, "error": "La cuenta no tiene acuerdo registrado."}
        dni = next(d for d, v in data["deudores"].items() if cuenta_id in v["cuentas"])
        destino = data["deudores"][dni]["telefono" if canal == "sms" else "email"]
        data["envios_link"].append({"cuenta_id": cuenta_id, "canal": canal, "destino": destino})
        # Se enmascara el destino para que el agente lo pueda leer sin exponer el dato completo.
        return {"ok": True, "canal": canal, "destino": destino[:4] + "****" + destino[-3:]}


def consultar_factura(cuenta_id: str) -> dict:
    """Factura subida por el cliente (procesada con visión) comparada con la deuda registrada."""
    data = _data()
    doc = data["documentos"].get(cuenta_id)
    if not doc:
        return {"ok": False, "error": "El cliente no subió ninguna factura para esta cuenta."}
    cuenta = data["cuentas"].get(cuenta_id, {})
    numeros_vencidos = {f["numero"] for f in cuenta.get("facturas_vencidas", [])}
    factura = doc["data"]
    numero = f"{factura.get('tipo')}-{factura.get('punto_venta')}-{factura.get('numero')}"
    return {"ok": True, "status": doc["status"], "errores": doc.get("errores", []), "factura": factura,
            "figura_como_vencida": numero in numeros_vencidos, "deuda_registrada": cuenta.get("deuda")}


TOOLS = [verificar_deudor, consultar_deuda, simular_plan, registrar_acuerdo, enviar_link_pago, consultar_factura]
