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


def texto_cambios(cambios, activos, referencia):
    """Compone el aviso a partir de los cambios detectados."""
    L = ["<b>AVIS · Oneways</b>"]
    nuevos = [c for c in cambios if c["tipo"] == "NUEVO"]
    fuera = [c for c in cambios if c["tipo"] == "DESAPARECIDO"]
    curso = [c for c in cambios if c["tipo"] == "EN_CURSO"]
    camb = [c for c in cambios if c["tipo"] == "CAMBIO"]

    def cabecera(r):
        return "%s %s · <b>%s</b> · %s→%s" % (
            _esc(r["tipo"]), _esc(r["num"]), _esc(r["matricula"] or "sin matrícula"),
            _esc(r["salida"]), _esc(r["devolucion"]))

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
        L.append("❌ <b>%s</b>" % ("ONEWAY ANULADO" if c.get("motivo") == "ANULADO"
                                  else "YA NO ES ONEWAY"))
        L.append("   " + cabecera(r))

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
