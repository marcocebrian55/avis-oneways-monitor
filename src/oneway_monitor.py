# -*- coding: utf-8 -*-
"""
Motor de análisis de ONEWAYS de Rentway (Fase 1).
- Lee los 2 Excels (Lista de reservas + Abiertos).
- Detecta oneways (oficina de salida != oficina de devolución).
- Construye un snapshot del día y lo compara con el del día anterior.
- Devuelve el resumen de oneways y la lista de CAMBIOS (nuevo/desaparecido/cambio de campo).
Sin Playwright ni avisos aún: esto es solo el cerebro, testeable con ficheros.
"""
import openpyxl, os, json, datetime


def _leer_hoja(path, hdr_row=5):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sh = wb.active
    rows = list(sh.iter_rows(values_only=True))
    hdr = rows[hdr_row - 1]
    idx = {c: j for j, c in enumerate(hdr) if c}
    data = [r for r in rows[hdr_row:] if r and r[0] not in (None, "")]
    return idx, data


def _col(idx, r, *nombres):
    for name in nombres:
        for k in idx:
            if k and name.lower() in k.lower():
                return r[idx[k]]
    return None


def _norm(v):
    return str(v).strip() if v not in (None, "") else ""


def _oficina_id(v):
    """De 'XLP4 Xtravans Las Palmas' o 'XLP4' saca el código 'XLP4'."""
    s = _norm(v)
    return s.split()[0] if s else ""


def _fecha(v):
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%d/%m/%Y %H:%M")
    return _norm(v)


def leer_oneways(reservas_path, abiertos_path):
    """Devuelve dict clave->registro de oneways detectados en ambos ficheros."""
    ow = {}

    # --- Lista de reservas ---
    idx, data = _leer_hoja(reservas_path)
    for r in data:
        sal = _col(idx, r, "ID de estación de salida", "ID de estacion de salida")
        dev = _col(idx, r, "ID de estación de devolucion", "ID de estacion de devolucion", "ID de estación de devolución")
        sal_id, dev_id = _oficina_id(sal), _oficina_id(dev)
        if not (sal_id and dev_id) or sal_id == dev_id:
            continue
        num = _norm(_col(idx, r, "N.º Reserva", "Reserva"))
        estado = _norm(_col(idx, r, "Estado"))
        elim = _norm(_col(idx, r, "Eliminado"))
        activo = (elim.lower() != "true") and ("cancel" not in estado.lower())
        clave = f"RES-{num}"
        ow[clave] = {
            "tipo": "Reserva", "num": num,
            "matricula": _norm(_col(idx, r, "Número de matrícula", "Numero de matricula")),
            "salida": sal_id, "of_salida": _norm(_col(idx, r, "Oficina de salida")),
            "devolucion": dev_id, "of_devolucion": _norm(_col(idx, r, "Oficina de devolución", "Oficina de devolucion")),
            "fecha_salida": _fecha(_col(idx, r, "Fecha de salida")),
            "fecha_llegada": _fecha(_col(idx, r, "Fecha llegada", "Fecha de llegada")),
            "cliente": _norm(_col(idx, r, "Nombre del cliente")),
            "estado": estado, "activo": activo,
        }

    # --- Abiertos (contratos) ---
    idx2, data2 = _leer_hoja(abiertos_path)
    for r in data2:
        sal_id = _oficina_id(_col(idx2, r, "ID de la oficina"))
        dev_id = _oficina_id(_col(idx2, r, "Oficina de devolución", "Oficina de devolucion"))
        if not (sal_id and dev_id) or sal_id == dev_id:
            continue
        num = _norm(_col(idx2, r, "N.º Contrato", "Contrato"))
        clave = f"CON-{num}"
        ow[clave] = {
            "tipo": "Contrato", "num": num,
            "matricula": _norm(_col(idx2, r, "Número de matrícula", "Numero de matricula")),
            "salida": sal_id, "of_salida": "",
            "devolucion": dev_id, "of_devolucion": _norm(_col(idx2, r, "Oficina de devolución", "Oficina de devolucion")),
            "fecha_salida": _fecha(_col(idx2, r, "Fecha de salida")),
            "fecha_llegada": _fecha(_col(idx2, r, "Fecha de regreso", "Fecha de retorno")),
            "cliente": _norm(_col(idx2, r, "Nombre del cliente")),
            "estado": "Abierto", "activo": True,
        }
    return ow


# campos cuyo cambio dispara aviso
CAMPOS_VIGILADOS = ["matricula", "salida", "devolucion", "fecha_salida", "fecha_llegada", "estado", "activo"]


def comparar(hoy, ayer):
    """Devuelve lista de cambios entre dos snapshots (dict clave->registro)."""
    cambios = []
    for clave, reg in hoy.items():
        if clave not in ayer:
            cambios.append({"tipo": "NUEVO", "clave": clave, "reg": reg})
        else:
            difs = []
            for c in CAMPOS_VIGILADOS:
                if str(ayer[clave].get(c)) != str(reg.get(c)):
                    difs.append((c, ayer[clave].get(c), reg.get(c)))
            if difs:
                cambios.append({"tipo": "CAMBIO", "clave": clave, "reg": reg, "difs": difs})
    for clave, reg in ayer.items():
        if clave not in hoy:
            cambios.append({"tipo": "DESAPARECIDO", "clave": clave, "reg": reg})
    return cambios


def resumen_texto(ow, cambios):
    L = []
    activos = [r for r in ow.values() if r["activo"]]
    L.append(f"ONEWAYS detectados: {len(ow)} (activos: {len(activos)})")
    L.append("")
    L.append("== ONEWAYS ACTIVOS ==")
    for r in sorted(activos, key=lambda x: x["fecha_salida"]):
        L.append(f"  {r['tipo']} {r['num']} | {r['matricula'] or '(sin matrícula)'} | "
                 f"{r['salida']}->{r['devolucion']} | salida {r['fecha_salida']} | {r['estado']} | {r['cliente']}")
    L.append("")
    L.append(f"== CAMBIOS respecto al día anterior: {len(cambios)} ==")
    if not cambios:
        L.append("  (sin cambios)")
    for c in cambios:
        r = c["reg"]
        base = f"{r['tipo']} {r['num']} ({r['matricula'] or 's/m'}, {r['salida']}->{r['devolucion']})"
        if c["tipo"] == "NUEVO":
            L.append(f"  [NUEVO ONEWAY] {base} salida {r['fecha_salida']} | {r['estado']}")
        elif c["tipo"] == "DESAPARECIDO":
            L.append(f"  [YA NO ONEWAY] {base}")
        else:
            for campo, viejo, nuevo in c["difs"]:
                L.append(f"  [CAMBIO] {base}: {campo}  '{viejo}' -> '{nuevo}'")
    return "\n".join(L)
