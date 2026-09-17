# -*- coding: utf-8 -*-
"""
Avisos por Telegram.

Sin dependencias externas: la API de Telegram es HTTP normal y se llama con
urllib, asi que no hay que añadir nada al .exe.

El token y el chat_id se guardan CIFRADOS con DPAPI (igual que las credenciales
de Rentway): el token da control total del bot a quien lo tenga.
"""
import json
import urllib.request
import urllib.parse

API = "https://api.telegram.org/bot%s/%s"
LIMITE = 4000          # Telegram corta en 4096 caracteres


def _llamar(token, metodo, datos=None, timeout=25):
    url = API % (token, metodo)
    cuerpo = urllib.parse.urlencode(datos).encode("utf-8") if datos else None
    with urllib.request.urlopen(url, data=cuerpo, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def comprobar(token):
    """Devuelve el nombre del bot si el token es valido."""
    r = _llamar(token, "getMe")
    if not r.get("ok"):
        raise RuntimeError(r.get("description", "token no valido"))
    return "@" + r["result"].get("username", "?")


def enviar(token, chat_id, texto, log=None):
    """Manda un mensaje. Devuelve True/False, nunca lanza: un fallo de avisos
    no debe tumbar la vigilancia."""
    try:
        if len(texto) > LIMITE:
            texto = texto[:LIMITE] + "\n… (recortado)"
        r = _llamar(token, "sendMessage",
                    {"chat_id": str(chat_id), "text": texto,
                     "parse_mode": "HTML", "disable_web_page_preview": "true"})
        if not r.get("ok") and log:
            log("  Telegram rechazo el mensaje: %s" % r.get("description"))
        return bool(r.get("ok"))
    except Exception as e:
        if log:
            log("  No pude enviar el aviso de Telegram: %s" % str(e)[:120])
        return False


def _esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def grupo_txt(r):
    """'grupo <b>SC</b> (Economic 4)', o '' si no se conoce.

    El grupo va DELANTE de la matricula por peticion de las oficinas
    (17/09/2026): con el grupo preparan el coche; la matricula concreta solo
    importa cuando ya se ha entregado."""
    g = (r.get("grupo") or "").strip()
    if not g:
        return ""
    d = (r.get("grupo_desc") or "").strip()
    return "grupo <b>%s</b>%s" % (_esc(g), " (%s)" % _esc(d) if d else "")


def matricula_txt(r):
    """La matricula SOLO si ya hay contrato, es decir, si el coche se ha
    entregado. Antes de eso es una pre-asignacion que cambia sola y confunde."""
    m = (r.get("matricula") or "").strip()
    if not r.get("contrato") or not m:
        return ""
    t = "matrícula <b>%s</b>" % _esc(m)
    gc = (r.get("grupo_coche") or "").strip()
    if gc and gc != (r.get("grupo") or "").strip():
        t += " (coche de grupo %s)" % _esc(gc)
    return t


def cabecera(r, ruta_negrita=False):
    """Linea que identifica un oneway, compartida por Telegram y correo."""
    ruta = "%s → %s" % (_esc(r.get("salida")), _esc(r.get("devolucion")))
    partes = ["%s %s" % (_esc(r.get("tipo")), _esc(r.get("num"))),
              grupo_txt(r),
              "<b>%s</b>" % ruta if ruta_negrita else ruta,
              matricula_txt(r)]
    return " · ".join(p for p in partes if p)


def titulo_baja(c):
    if c.get("motivo") == "ANULADO":
        return "ONEWAY ANULADO"
    if c.get("motivo") == "MISMA_OFICINA":
        return "YA NO ES ONEWAY — se devuelve en la misma oficina"
    return "YA NO ES ONEWAY"


def texto_cambios(cambios, activos, referencia):
    """Compone el aviso a partir de los cambios detectados."""
    L = ["<b>AVIS · Oneways</b>"]
    nuevos = [c for c in cambios if c["tipo"] == "NUEVO"]
    fuera = [c for c in cambios if c["tipo"] in ("DESAPARECIDO", "ANULADO")]
    curso = [c for c in cambios if c["tipo"] == "EN_CURSO"]
    camb = [c for c in cambios if c["tipo"] == "CAMBIO"]

    for c in nuevos:
        r = c["reg"]
        L.append("")
        L.append("🆕 <b>NUEVO ONEWAY</b>")
        L.append("   " + cabecera(r))
        L.append("   salida %s · llegada %s" % (_esc(r["fecha_salida"]), _esc(r["fecha_llegada"])))
        if r.get("cliente"):
            L.append("   cliente: %s" % _esc(r["cliente"]))
        tel = r.get("telefono") or r.get("telefono_conductor")
        if tel:
            L.append("   tel: %s" % _esc(tel))
        if r.get("observaciones"):
            L.append("   obs: %s" % _esc(r["observaciones"][:120]))

    for c in fuera:
        r = c["reg"]
        L.append("")
        L.append("❌ <b>%s</b>" % ("ONEWAY ANULADO" if c["tipo"] == "ANULADO"
                                  else titulo_baja(c)))
        L.append("   " + cabecera(r))
        if c["tipo"] == "ANULADO" and r.get("estado"):
            L.append("   %s · salía %s" % (_esc(r["estado"]), _esc(r.get("fecha_salida"))))

    for c in curso:
        r = c["reg"]
        L.append("")
        L.append("🚗 <b>ONEWAY EN CURSO</b> — el cliente ha recogido el coche")
        L.append("   " + cabecera(r))
        if r.get("contrato"):
            L.append("   contrato %s" % _esc(r["contrato"]))
        L.append("   devolver en <b>%s</b> el %s" % (_esc(r["devolucion"]),
                                                     _esc(r["fecha_llegada"])))

    for c in camb:
        r = c["reg"]
        L.append("")
        L.append("✏️ <b>CAMBIO</b>")
        L.append("   " + cabecera(r))
        for campo, viejo, nuevo in c["difs"]:
            L.append("   %s: %s → %s" % (_esc(campo), _esc(viejo), _esc(nuevo)))

    L.append("")
    L.append("<i>%d oneway(s) activos · comparado con %s</i>"
             % (len(activos), _esc(referencia or "primera pasada")))
    return "\n".join(L)
