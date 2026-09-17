# -*- coding: utf-8 -*-
"""
Hoja de Google con los oneways, puesta al dia en cada pasada.

Peticion de las oficinas del 17/09/2026: ver los oneways futuros y en curso en
una hoja, por colores segun su estado, y que los terminados salgan a otra
pestaña. Tres pestañas:

  Oneways      se REESCRIBE entera en cada pasada: es la foto de ahora.
  Completados  se AÑADE: devueltos, anulados, sin recoger. Se guardan 30 dias.
  Alertas      se AÑADE: cada aviso que se ha mandado a las oficinas. 30 dias.

COMO LLEGA AL DRIVE DE EMPRESA. El servidor no tiene cuenta de Google. La hoja
lleva dentro un Apps Script (`hoja/Codigo.gs` del repositorio) publicado como
aplicacion web que se ejecuta COMO SU DUEÑO; el servidor le hace un POST con
los datos y una clave compartida. Asi no hay proyecto de Google Cloud ni
credenciales de Google en el servidor: solo la URL del script y la clave, que
unicamente permiten escribir en esa hoja.

TODO SE DECIDE AQUI, NO EN EL SCRIPT. Estado, color, orden y formato de cada
fila se calculan en Python, que tiene pruebas; el script solo pinta lo que le
llega. Un error de logica en un .gs pegado a mano en un navegador no lo caza
nadie.

Solo biblioteca estandar. Un fallo aqui NUNCA tumba la pasada: la hoja es una
vista, los avisos por correo y Telegram siguen siendo lo que manda.
"""
import os, json, hashlib, datetime, urllib.request

DIAS_GUARDAR = 30
COLA = "hoja_pendiente.json"          # completados/alertas que no llegaron

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


# ---------------- configuracion ----------------
def cargar_config(base):
    """{"url", "clave"} o None si la hoja no esta configurada.

    Se lee de la seccion "hoja" de configuracion.json (en el servidor,
    /var/lib/oneways/configuracion.json). El entorno manda, como en el resto.
    """
    url, clave = os.environ.get("HOJA_URL"), os.environ.get("HOJA_CLAVE")
    if not (url and clave):
        for d in (base, os.path.dirname(os.path.abspath(base))):
            p = os.path.join(d, "configuracion.json")
            if os.path.exists(p):
                try:
                    with open(p, encoding="utf-8-sig") as f:
                        h = json.load(f).get("hoja") or {}
                    url, clave = h.get("url"), h.get("clave")
                except Exception:
                    pass
                break
    if not (url and clave):
        return None
    return {"url": url.strip(), "clave": clave.strip()}


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


def construir(ow, cambios, silenciosos, islas, avisado, ahora=None):
    """El cuerpo del POST, sin la clave. `avisado`: si esta pasada mando los
    avisos (con --sin-avisos no hubo alertas que apuntar)."""
    ahora = ahora or datetime.datetime.now()
    limite = ahora - datetime.timedelta(days=DIAS_GUARDAR)
    return {
        "actualizado": ahora.strftime("%d/%m/%Y %H:%M"),
        "leyenda": [[k, v[1]] for k, v in ESTADOS.items()],
        "oneways": tabla_oneways(ow, islas, ahora),
        "completados": {"cabecera": CAB_COMPLETADOS, "filas": [], "gris": GRIS,
                        "fechas": [0, 10, 11]},
        "alertas": {"cabecera": CAB_ALERTAS, "filas": [], "fechas": [0]},
        "nuevos_completados": filas_completados(cambios, silenciosos, islas, ahora),
        "nuevas_alertas": filas_alertas(cambios, ahora) if avisado else [],
        "limite": _serial(limite),
    }


# ---------------- envio ----------------
def _leer_cola(base):
    try:
        with open(os.path.join(base, COLA), encoding="utf-8") as f:
            d = json.load(f)
        return d.get("completados", []), d.get("alertas", [])
    except Exception:
        return [], []


def _guardar_cola(base, completados, alertas):
    p = os.path.join(base, COLA)
    if not completados and not alertas:
        if os.path.exists(p):
            os.remove(p)
        return
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"completados": completados[-500:], "alertas": alertas[-500:]}, f,
                  ensure_ascii=False)


def enviar(url, cuerpo, timeout=90):
    """POST al Apps Script. Devuelve el JSON de respuesta.

    OJO: Google contesta al POST con un 302 hacia googleusercontent.com, y ahi
    esta la respuesta de verdad. urllib sigue ese 302 convirtiendolo en GET,
    que es exactamente lo que hay que hacer (el script ya se ejecuto en el
    POST). Si algun dia se cambia de libreria, que siga el redirect igual.
    """
    datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=datos, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        texto = r.read().decode("utf-8", "replace")
    try:
        return json.loads(texto)
    except ValueError:
        # Una pagina HTML en vez de JSON: casi siempre es la pantalla de
        # "inicia sesion" de Google, o sea que la aplicacion web no esta
        # publicada para "Cualquier usuario".
        raise RuntimeError("la hoja no devolvio JSON (¿publicada para 'Cualquier "
                           "usuario'?): %s" % " ".join(texto.split())[:120])


def sincronizar(ow, cambios, silenciosos, islas, base, avisado=True, log=None, ahora=None):
    """Pone la hoja al dia. Devuelve True/False, o None si no esta configurada.
    NUNCA lanza.

    Completados y alertas se AÑADEN, asi que si un envio falla se perderian.
    Se guardan en una cola y se reenvian en la siguiente pasada; el script
    descarta los que ya tenga por su id, asi que reenviar no duplica.
    """
    log = log or (lambda m: None)
    try:
        cfg = cargar_config(base)
        if not cfg:
            return None
        cuerpo = construir(ow, cambios, silenciosos, islas, avisado, ahora)
        cola_c, cola_a = _leer_cola(base)
        cuerpo["completados"]["filas"] = cola_c + cuerpo.pop("nuevos_completados")
        cuerpo["alertas"]["filas"] = cola_a + cuerpo.pop("nuevas_alertas")
        cuerpo["clave"] = cfg["clave"]
        try:
            r = enviar(cfg["url"], cuerpo)
            if not r.get("ok"):
                raise RuntimeError(r.get("error") or "respuesta sin ok")
        except Exception as e:
            _guardar_cola(base, cuerpo["completados"]["filas"], cuerpo["alertas"]["filas"])
            log("Hoja de Google NO actualizada: %s" % str(e)[:160])
            return False
        _guardar_cola(base, [], [])
        log("Hoja de Google actualizada: %d oneway(s), +%s completado(s), +%s alerta(s)"
            % (len(cuerpo["oneways"]["filas"]), r.get("completados", "?"),
               r.get("alertas", "?")))
        return True
    except Exception as e:
        log("Fallo preparando la hoja de Google: %s" % str(e)[:160])
        return False
