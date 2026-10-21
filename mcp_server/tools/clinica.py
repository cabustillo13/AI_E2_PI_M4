"""Clínica San Martín — mock de la agenda de turnos.

Reglas de negocio que viven en las tools (no en el prompt):
- Cancelar / reprogramar: hasta 24 h antes.
- Cardiología y traumatología requieren orden médica vigente (la carga el endpoint de visión).
Los errores se devuelven como {"ok": False, "error": ...}: son errores recuperables que el LLM
le explica al paciente (M3 · loop engineering), no excepciones.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from mcp_server import store

DOMAIN = "clinica"
REQUIEREN_ORDEN = {"cardiologia", "traumatologia"}
HORARIOS = ["09:00", "10:00", "11:30", "15:00", "16:30"]

PROFESIONALES = [
    {"id": "P1", "nombre": "Dra. Ana Ruiz", "especialidad": "cardiologia"},
    {"id": "P2", "nombre": "Dr. Martín López", "especialidad": "clinica_medica"},
    {"id": "P3", "nombre": "Dra. Sofía Méndez", "especialidad": "dermatologia"},
    {"id": "P4", "nombre": "Dr. Pablo Herrera", "especialidad": "traumatologia"},
]


def _dias_habiles(desde: date, cantidad: int) -> list[date]:
    dias, d = [], desde
    while len(dias) < cantidad:
        d += timedelta(days=1)
        if d.weekday() < 5:  # lunes a viernes
            dias.append(d)
    return dias


def seed() -> dict:
    hoy = store.today()
    dias = _dias_habiles(hoy, 10)
    slots = {}
    for prof in PROFESIONALES:
        for d in dias:
            for hora in HORARIOS:
                slot_id = f"{prof['id']}-{d.isoformat()}-{hora.replace(':', '')}"
                slots[slot_id] = {"profesional_id": prof["id"], "inicio": f"{d.isoformat()}T{hora}", "libre": True}

    # Turnos existentes para poder demostrar reprogramar / cancelar.
    turno_slot = f"P2-{dias[1].isoformat()}-1000"
    turno_slot_juan = f"P3-{dias[2].isoformat()}-1130"
    slots[turno_slot]["libre"] = slots[turno_slot_juan]["libre"] = False
    return {
        "pacientes": {
            "30111222": {"nombre": "María González", "fecha_nacimiento": "1985-04-12", "obra_social": "OSDE"},
            "28999888": {"nombre": "Juan Pérez", "fecha_nacimiento": "1979-11-02", "obra_social": "Swiss Medical"},
            "40123456": {"nombre": "Lucía Fernández", "fecha_nacimiento": "1998-07-23", "obra_social": "Particular"},
        },
        "slots": slots,
        "turnos": {
            "T-1000": {"dni": "28999888", "slot_id": turno_slot_juan, "estado": "confirmado"},
            "T-1001": {"dni": "30111222", "slot_id": turno_slot, "estado": "confirmado"},
        },
        # Documentos procesados por /vision (clave = DNI). Juan ya tiene una orden de cardiología.
        "documentos": {
            "28999888": {
                "status": "valido",
                "data": {
                    "paciente_nombre": "Juan Pérez", "paciente_dni": "28999888", "obra_social": "Swiss Medical",
                    "medico_nombre": "Dr. Ricardo Paz", "matricula": "MN 123456",
                    "especialidad_derivada": "cardiologia", "practica": "Consulta y ecocardiograma",
                    "fecha_emision": (hoy - timedelta(days=5)).isoformat(), "firma_presente": True,
                },
                "vigente": True,
            }
        },
        "proximo_turno": 1002,
    }


def _data() -> dict:
    return store.load(DOMAIN, seed)


def _describir_slot(data: dict, slot_id: str) -> dict:
    slot = data["slots"][slot_id]
    prof = next(p for p in PROFESIONALES if p["id"] == slot["profesional_id"])
    return {"slot_id": slot_id, "inicio": slot["inicio"], "cuando": store.fecha_legible(slot["inicio"]),
            "profesional": prof["nombre"], "especialidad": prof["especialidad"]}


def _faltan_24h(data: dict, slot_id: str) -> bool:
    inicio = datetime.fromisoformat(data["slots"][slot_id]["inicio"])
    return inicio - store.now() >= timedelta(hours=24)


# ─────────────────────────────── Tools ───────────────────────────────


def verificar_paciente(dni: str, fecha_nacimiento: str) -> dict:
    """Verifica la identidad del paciente con DNI y fecha de nacimiento (YYYY-MM-DD).
    Llamar SIEMPRE antes de consultar o modificar turnos."""
    paciente = _data()["pacientes"].get(store.solo_digitos(dni))
    if not paciente or paciente["fecha_nacimiento"] != fecha_nacimiento.strip():
        return {"ok": False, "error": "No encontramos un paciente con esos datos."}
    return {"ok": True, "paciente": {"dni": dni, "nombre": paciente["nombre"], "obra_social": paciente["obra_social"]}}


def buscar_disponibilidad(especialidad: str, fecha: str | None = None, franja: str | None = None) -> dict:
    """Busca hasta 5 turnos libres. especialidad: clinica_medica | cardiologia | dermatologia | traumatologia.
    fecha opcional (YYYY-MM-DD) para buscar desde ese día. franja opcional: 'manana' | 'tarde'."""
    data = _data()
    profs = {p["id"] for p in PROFESIONALES if p["especialidad"] == especialidad}
    if not profs:
        return {"ok": False, "error": f"Especialidad desconocida: {especialidad}"}
    libres = []
    for slot_id, slot in sorted(data["slots"].items(), key=lambda kv: kv[1]["inicio"]):
        if not slot["libre"] or slot["profesional_id"] not in profs:
            continue
        if fecha and slot["inicio"][:10] < fecha:
            continue
        hora = int(slot["inicio"][11:13])
        if franja == "manana" and hora >= 13 or franja == "tarde" and hora < 13:
            continue
        libres.append(_describir_slot(data, slot_id))
        if len(libres) == 5:
            break
    return {"ok": True, "turnos_libres": libres}


def agendar_turno(dni: str, slot_id: str) -> dict:
    """Reserva el turno slot_id para el paciente (ya verificado)."""
    with store.edit(DOMAIN, seed) as data:
        if dni not in data["pacientes"]:
            return {"ok": False, "error": "Paciente inexistente."}
        slot = data["slots"].get(slot_id)
        if not slot or not slot["libre"]:
            return {"ok": False, "error": "Ese turno ya no está disponible."}
        especialidad = _describir_slot(data, slot_id)["especialidad"]
        if especialidad in REQUIEREN_ORDEN:
            doc = data["documentos"].get(dni)
            orden_ok = doc and doc["status"] == "valido" and doc.get("vigente") \
                and doc["data"].get("especialidad_derivada") == especialidad
            if not orden_ok:
                return {"ok": False, "error": f"{especialidad} requiere orden médica vigente cargada en la web."}
        turno_id = f"T-{data['proximo_turno']}"
        data["proximo_turno"] += 1
        slot["libre"] = False
        data["turnos"][turno_id] = {"dni": dni, "slot_id": slot_id, "estado": "confirmado"}
        return {"ok": True, "turno_id": turno_id, **_describir_slot(data, slot_id)}


def listar_turnos(dni: str) -> dict:
    """Lista los turnos confirmados del paciente."""
    data = _data()
    turnos = [
        {"turno_id": tid, **_describir_slot(data, t["slot_id"])}
        for tid, t in data["turnos"].items()
        if t["dni"] == dni and t["estado"] == "confirmado"
    ]
    return {"ok": True, "turnos": turnos}


def reprogramar_turno(turno_id: str, nuevo_slot_id: str) -> dict:
    """Mueve un turno confirmado a otro horario libre (hasta 24 h antes del turno original)."""
    with store.edit(DOMAIN, seed) as data:
        turno = data["turnos"].get(turno_id)
        if not turno or turno["estado"] != "confirmado":
            return {"ok": False, "error": "Turno inexistente o ya cancelado."}
        if not _faltan_24h(data, turno["slot_id"]):
            return {"ok": False, "error": "Faltan menos de 24 h: no se puede reprogramar por este medio."}
        nuevo = data["slots"].get(nuevo_slot_id)
        if not nuevo or not nuevo["libre"]:
            return {"ok": False, "error": "El nuevo horario no está disponible."}
        if _describir_slot(data, nuevo_slot_id)["especialidad"] != _describir_slot(data, turno["slot_id"])["especialidad"]:
            return {"ok": False, "error": "El nuevo horario es de otra especialidad."}
        data["slots"][turno["slot_id"]]["libre"] = True
        nuevo["libre"] = False
        turno["slot_id"] = nuevo_slot_id
        return {"ok": True, "turno_id": turno_id, **_describir_slot(data, nuevo_slot_id)}


def cancelar_turno(turno_id: str) -> dict:
    """Cancela un turno confirmado (hasta 24 h antes)."""
    with store.edit(DOMAIN, seed) as data:
        turno = data["turnos"].get(turno_id)
        if not turno or turno["estado"] != "confirmado":
            return {"ok": False, "error": "Turno inexistente o ya cancelado."}
        if not _faltan_24h(data, turno["slot_id"]):
            return {"ok": False, "error": "Faltan menos de 24 h: no se puede cancelar por este medio."}
        turno["estado"] = "cancelado"
        data["slots"][turno["slot_id"]]["libre"] = True
        return {"ok": True, "turno_id": turno_id, "estado": "cancelado"}


def consultar_orden_medica(dni: str) -> dict:
    """Devuelve la orden médica que el paciente cargó por la web (procesada con visión), si existe."""
    doc = _data()["documentos"].get(dni)
    if not doc:
        return {"ok": False, "error": "El paciente no tiene orden médica cargada."}
    return {"ok": True, "orden": doc}


TOOLS = [verificar_paciente, buscar_disponibilidad, agendar_turno, listar_turnos,
         reprogramar_turno, cancelar_turno, consultar_orden_medica]
