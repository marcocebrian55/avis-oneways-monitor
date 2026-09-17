# -*- coding: utf-8 -*-
"""
Hoja de Google con los oneways, puesta al dia en cada pasada.

Peticion de las oficinas del 17/09/2026: ver los oneways futuros y en curso en
una hoja, por colores segun su estado, y que los terminados salgan a otra
pestaña. Tres pestañas:

  Oneways      futuros y en curso, lo urgente arriba.
  Completados  devueltos, anulados, sin recoger. Ultimos 30 dias.
  Alertas      cada aviso que se ha mandado a las oficinas. Ultimos 30 dias.

LA HOJA VIENE A BUSCAR LOS DATOS, NO SE LOS MANDAMOS. La primera version hacia
un POST a un Apps Script publicado como aplicacion web, pero el Google
Workspace del grupo solo deja publicarlas para "cualquiera de domingoalonso" o
"solo yo" (comprobado el 17/09/2026): desde el servidor, sin cuenta de Google,
cualquier llamada acababa en la pantalla de inicio de sesion. Asi que se
invierte:

  1. Cada pasada escribe `publica/hoja_datos.json` (este modulo).
  2. Tailscale Funnel sirve ESE fichero por HTTPS en una ruta con un token
     largo (ver hoja/LEEME.md). Es lo unico del servidor abierto a internet.
  3. El script de la hoja (hoja/Codigo.gs) tiene un disparador cada 10 min que
     lo descarga con UrlFetchApp y repinta si ha cambiado.

Completados y Alertas se guardan AQUI (`hoja_historial.json`), no en la hoja:
cada fichero trae los 30 dias enteros y el script reescribe las pestañas sin
llevar la cuenta de nada. Si una descarga falla, la siguiente trae todo.

TODO SE DECIDE AQUI, NO EN EL SCRIPT. Estado, color, orden y formato se
calculan en Python, que tiene pruebas; el script solo pinta.

Solo biblioteca estandar. Un fallo aqui NUNCA tumba la pasada: la hoja es una
vista, los avisos por correo y Telegram siguen siendo lo que manda.
"""
import os, json, hashlib, datetime

DIAS_GUARDAR = 30
CARPETA_PUBLICA = "publica"           # lo UNICO que sirve Funnel
FICHERO_DATOS = "hoja_datos.json"
HISTORIAL = "hoja_historial.json"     # completados y alertas de 30 dias

# Estado -> (orden en la hoja, color de fondo). Colores suaves: la hoja se lee
# de un vistazo y el texto tiene que seguir siendo legible.
ESTADOS = {
    "Atrasado":        (0, "#F8CBCB"),   # contrato abierto con la devolucion pasada
    "Se devuelve hoy": (1, "#FFE0B8"),
    "Sale hoy":        (2, "#FFF4C2"),
    "En curso":        (3, "#D8F0D8"),
    "Futuro":          (4, "#DCEBFA"),
}
GRIS = "#EEEEEE"

MOTIVOS = {
    "TERMINADO":     "Completado (coche devuelto)",
    "SIN_RECOGER":   "Salida pasada sin contrato",
    "ANULADO":       "Anulado",
    "MISMA_OFICINA": "Ya no es oneway (se devuelve en la misma oficina)",
    "":              "Ya no es oneway",
}

TIPOS_AVISO = {
    "NUEVO": "Nuevo oneway", "ANULADO": "Anulado", "EN_CURSO": "En curso (recogido)",
    "CAMBIO": "Cambio", "DESAPARECIDO": "Baja",
}

CAB_ONEWAYS = ["Estado", "Reserva", "Contrato", "Grupo", "Descripción grupo",
               "Salida", "Isla salida", "Devolución", "Isla devolución",
               "Fecha salida", "Fecha devolución", "Matrícula", "Cliente",
               "Teléfono", "Observaciones"]
CAB_COMPLETADOS = ["Cerrado", "Motivo", "Reserva", "Contrato", "Grupo",
                   "Descripción grupo", "Salida", "Isla salida", "Devolución",
                   "Isla devolución", "Fecha salida", "Fecha devolución",
                   "Matrícula", "Cliente", "id"]
CAB_ALERTAS = ["Fecha", "Aviso", "Reserva", "Contrato", "Grupo", "Ruta", "Detalle", "id"]


# ---------------- fechas ----------------
def _fecha(txt):
    try:
        return datetime.datetime.strptime(str(txt), "%d/%m/%Y %H:%M")
    except Exception:
        return None


def _serial(dt):
    """Fecha como numero de serie de hoja de calculo (dias desde 30/12/1899).

    Se manda asi y no como texto ni como fecha ISO a proposito: un numero no
    depende de la zona horaria del script ni de la de la hoja (que pueden ser
    Madrid y no Canarias), y la columna se puede ordenar y filtrar como fecha.
    """
    if not dt:
        return ""
    return round((dt - datetime.datetime(1899, 12, 30)).total_seconds() / 86400.0, 6)


# ---------------- filas ----------------
def estado(reg, ahora):
    """Estado de un oneway ACTIVO en la hoja, visto desde `ahora`."""
    salida, llegada = _fecha(reg.get("fecha_salida")), _fecha(reg.get("fecha_llegada"))
    recogido = bool(reg.get("contrato")) or "with ra" in str(reg.get("estado") or "").lower()
    if recogido:
        if llegada and llegada < ahora:
            return "Atrasado"
        if llegada and llegada.date() == ahora.date():
            return "Se devuelve hoy"
        return "En curso"
    if salida and salida.date() <= ahora.date():
        return "Sale hoy"
    return "Futuro"


def _num_reserva(reg):
    return reg.get("num") if reg.get("tipo") == "Reserva" else ""


def _num_contrato(reg):
    return reg.get("contrato") or (reg.get("num") if reg.get("tipo") == "Contrato" else "")


def _comunes(reg, islas):
    """Columnas compartidas por Oneways y Completados, desde Reserva."""
    return [_num_reserva(reg), _num_contrato(reg), reg.get("grupo") or "",
            reg.get("grupo_desc") or "", reg.get("salida") or "",
            islas.get(str(reg.get("salida") or "")) or "",
            reg.get("devolucion") or "", islas.get(str(reg.get("devolucion") or "")) or "",
            _serial(_fecha(reg.get("fecha_salida"))),
            _serial(_fecha(reg.get("fecha_llegada"))),
            # la matricula solo con contrato, igual que en los avisos
            (reg.get("matricula") or "") if reg.get("contrato") else "",
            reg.get("cliente") or ""]


def tabla_oneways(ow, islas, ahora):
    filas = []
    for reg in ow.values():
        if not reg.get("activo"):
            continue
        est = estado(reg, ahora)
        fila = [est] + _comunes(reg, islas) + [
            reg.get("telefono") or reg.get("telefono_conductor") or "",
            (reg.get("observaciones") or "")[:200]]
        filas.append((ESTADOS[est][0], _fecha(reg.get("fecha_salida")) or ahora, fila))
    # Lo urgente arriba (atrasados, devoluciones y salidas de hoy) y, dentro
    # de cada estado, por fecha de salida.
    filas.sort(key=lambda x: (x[0], x[1]))
    return {"cabecera": CAB_ONEWAYS, "filas": [f for _, _, f in filas],
            "colores": [ESTADOS[f[0]][1] for _, _, f in filas],
            "fechas": [9, 10]}


def _id(*partes):
    return hashlib.sha1("|".join(str(p) for p in partes).encode("utf-8")).hexdigest()[:16]


def filas_completados(cambios, silenciosos, islas, ahora):
    """Lo que sale de la lista de oneways en esta pasada, con su motivo."""
    salen = [(c["reg"], c.get("motivo") or "") for c in cambios if c["tipo"] == "DESAPARECIDO"]
    salen += [(c["reg"], "ANULADO") for c in cambios if c["tipo"] == "ANULADO"]
    salen += [(s["reg"], s["motivo"]) for s in silenciosos or []]
    sello = ahora.strftime("%Y-%m-%d %H:%M")
    return [[_serial(ahora), MOTIVOS.get(m, m)] + _comunes(r, islas)
            + [_id("C", r.get("tipo"), r.get("num"), m, sello)]
            for r, m in salen]


def _detalle_aviso(c):
    r = c["reg"]
    if c["tipo"] == "CAMBIO":
        return "; ".join("%s: %s → %s" % d for d in c.get("difs") or [])
    if c["tipo"] == "EN_CURSO":
        return "matrícula %s · devolver el %s" % (r.get("matricula") or "?", r.get("fecha_llegada"))
    if c["tipo"] == "DESAPARECIDO":
        return MOTIVOS.get(c.get("motivo") or "", "")
    return "sale el %s" % r.get("fecha_salida")


def filas_alertas(cambios, ahora):
    sello = ahora.strftime("%Y-%m-%d %H:%M")
    out = []
    for c in cambios:
        r = c["reg"]
        out.append([_serial(ahora), TIPOS_AVISO.get(c["tipo"], c["tipo"]),
                    _num_reserva(r), _num_contrato(r), r.get("grupo") or "",
                    "%s → %s" % (r.get("salida"), r.get("devolucion")),
                    _detalle_aviso(c),
                    _id("A", c["tipo"], r.get("tipo"), r.get("num"), sello)])
    return out


# ---------------- historial y publicacion ----------------
def _leer_json(ruta, defecto):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defecto


def _escribir_atomico(ruta, datos):
    """Escribe a un temporal y lo renombra: Funnel puede estar sirviendo el
    fichero justo en ese momento, y nunca debe ver uno a medio escribir."""
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)
    os.replace(tmp, ruta)


def acumular(previas, nuevas, limite):
    """Añade sin repetir id (ultima columna), quita lo anterior a `limite`
    (primera columna) y deja lo mas reciente arriba."""
    vistos, out = set(), []
    for f in list(nuevas) + list(previas):
        if f[-1] in vistos or not f[0] or f[0] < limite:
            continue
        vistos.add(f[-1])
        out.append(f)
    out.sort(key=lambda f: f[0], reverse=True)
    return out


def construir(ow, cambios, silenciosos, islas, avisado, historial, ahora=None):
    """El contenido de hoja_datos.json. Actualiza `historial` en el sitio.

    `avisado`: si esta pasada mando los avisos (con --sin-avisos no hubo
    alertas que apuntar)."""
    ahora = ahora or datetime.datetime.now()
    limite = _serial(ahora - datetime.timedelta(days=DIAS_GUARDAR))
    historial["completados"] = acumular(
        historial.get("completados", []),
        filas_completados(cambios, silenciosos, islas, ahora), limite)
    historial["alertas"] = acumular(
        historial.get("alertas", []),
        filas_alertas(cambios, ahora) if avisado else [], limite)
    return {
        # El script repinta solo si cambia el sello.
        "sello": ahora.strftime("%Y%m%d%H%M%S"),
        "actualizado": ahora.strftime("%d/%m/%Y %H:%M"),
        "leyenda": [[k, v[1]] for k, v in ESTADOS.items()],
        "oneways": tabla_oneways(ow, islas, ahora),
        "completados": {"cabecera": CAB_COMPLETADOS, "filas": historial["completados"],
                        "gris": GRIS, "fechas": [0, 10, 11]},
        "alertas": {"cabecera": CAB_ALERTAS, "filas": historial["alertas"],
                    "fechas": [0]},
    }


def publicar(ow, cambios, silenciosos, islas, base, avisado=True, log=None, ahora=None):
    """Escribe publica/hoja_datos.json. Devuelve True/False y NUNCA lanza."""
    log = log or (lambda m: None)
    try:
        ruta_hist = os.path.join(base, HISTORIAL)
        historial = _leer_json(ruta_hist, {})
        datos = construir(ow, cambios, silenciosos, islas, avisado, historial, ahora)
        carpeta = os.path.join(base, CARPETA_PUBLICA)
        os.makedirs(carpeta, exist_ok=True)
        _escribir_atomico(os.path.join(carpeta, FICHERO_DATOS), datos)
        _escribir_atomico(ruta_hist, historial)
        log("Datos de la hoja listos: %d oneway(s), %d completado(s), %d alerta(s)"
            % (len(datos["oneways"]["filas"]), len(historial["completados"]),
               len(historial["alertas"])))
        return True
    except Exception as e:
        log("Fallo preparando los datos de la hoja: %s" % str(e)[:160])
        return False
