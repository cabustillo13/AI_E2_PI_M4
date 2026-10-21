"""Reglas de negocio de los mocks MCP (se llaman las funciones directo, sin MCP)."""

from datetime import datetime

from mcp_server import store
from mcp_server.tools import clinica, cobranzas, logistica

# ─────────────── Clínica ───────────────


def test_verificar_paciente():
    assert clinica.verificar_paciente("30111222", "1985-04-12")["ok"]
    assert not clinica.verificar_paciente("30111222", "1985-04-13")["ok"]


def test_agendar_y_no_duplicar():
    slot = clinica.buscar_disponibilidad("clinica_medica")["turnos_libres"][0]["slot_id"]
    assert clinica.agendar_turno("40123456", slot)["ok"]
    assert not clinica.agendar_turno("30111222", slot)["ok"]  # ya ocupado


def test_cardiologia_requiere_orden():
    slot = clinica.buscar_disponibilidad("cardiologia")["turnos_libres"][0]["slot_id"]
    resp = clinica.agendar_turno("40123456", slot)  # Lucía no tiene orden cargada
    assert not resp["ok"] and "orden" in resp["error"]
    assert clinica.agendar_turno("28999888", slot)["ok"]  # Juan sí tiene orden vigente


def test_franja_tarde():
    turnos = clinica.buscar_disponibilidad("dermatologia", franja="tarde")["turnos_libres"]
    assert turnos and all(int(t["inicio"][11:13]) >= 13 for t in turnos)


def test_reprogramar_y_cancelar():
    turno = clinica.listar_turnos("30111222")["turnos"][0]
    nuevo = clinica.buscar_disponibilidad("clinica_medica", fecha="2026-11-10")["turnos_libres"][0]["slot_id"]
    assert clinica.reprogramar_turno(turno["turno_id"], nuevo)["ok"]
    assert clinica.cancelar_turno(turno["turno_id"])["ok"]
    assert clinica.listar_turnos("30111222")["turnos"] == []


def test_no_cancelar_con_menos_de_24h(monkeypatch):
    slot = clinica.buscar_disponibilidad("dermatologia")["turnos_libres"][0]  # martes 3/11 9 h
    turno = clinica.agendar_turno("40123456", slot["slot_id"])
    monkeypatch.setattr(store, "now", lambda: datetime(2026, 11, 2, 10, 0))  # faltan 23 h
    resp = clinica.cancelar_turno(turno["turno_id"])
    assert not resp["ok"] and "24 h" in resp["error"]


# ─────────────── Logística ───────────────


def test_envio_requiere_dni_correcto():
    assert logistica.consultar_envio("rl-100234", "33444555")["ok"]
    assert not logistica.consultar_envio("RL-100234", "11111111")["ok"]


def test_reprogramar_entrega_fallida():
    opciones = logistica.opciones_reprogramacion("RL-100235")["opciones"]
    elegida = opciones[1]
    resp = logistica.reprogramar_entrega("RL-100235", elegida["fecha"], elegida["franja"])
    assert resp["ok"] and resp["franja"] == elegida["franja"]


def test_no_reprogramar_envio_en_transito_ni_fuera_de_opciones():
    assert not logistica.opciones_reprogramacion("RL-100234")["ok"]
    assert not logistica.reprogramar_entrega("RL-100235", "2030-01-01", "manana")["ok"]


def test_remito_no_expone_dni_completo():
    resp = logistica.consultar_remito("RL-100236")
    assert resp["receptor_dni_final"] == "666" and "14555666" not in str(resp)


# ─────────────── Cobranzas ───────────────


def test_plan_segun_mora():
    assert cobranzas.simular_plan("C-5001", 3)["ok"]                 # 18 días → hasta 3
    assert not cobranzas.simular_plan("C-5001", 4)["ok"]
    plan = cobranzas.simular_plan("C-5002", 6)                       # 41 días → 6 con 5 %
    assert plan["ok"] and plan["total"] == round(128_500 * 1.05, 2)
    assert not cobranzas.simular_plan("C-5003", 1)["ok"]             # 75 días → derivar


def test_cuota_minima():
    resp = cobranzas.simular_plan("C-5001", 3)  # 45.800 / 3 = 15.266 → ok
    assert resp["ok"] and resp["monto_cuota"] >= cobranzas.CUOTA_MINIMA


def test_acuerdo_y_link():
    resp = cobranzas.registrar_acuerdo("C-5001", 2, "2026-11-05")
    assert resp["ok"] and resp["link_pago"].startswith(cobranzas.LINK_BASE)
    assert not cobranzas.registrar_acuerdo("C-5001", 2, "2026-11-05")["ok"]  # ya tiene acuerdo
    envio = cobranzas.enviar_link_pago("C-5001", "sms")
    assert envio["ok"] and "****" in envio["destino"]


def test_acuerdo_fecha_fuera_de_rango():
    assert not cobranzas.registrar_acuerdo("C-5001", 1, "2026-12-01")["ok"]
