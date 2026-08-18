# -*- coding: utf-8 -*-
"""
Escucha de comandos de Telegram.

Permite escribir /revisar en el grupo y que el monitor haga una pasada en el
momento, sin esperar a la siguiente hora programada.

COMO FUNCIONA: 'long polling'. Se pide a Telegram getUpdates con timeout=50;
la conexion se queda abierta y solo responde cuando llega un mensaje (o a los
50 s, vacia). No hay que abrir puertos ni montar un servidor, y el consumo
mientras no pasa nada es practicamente cero.

POR QUE HACE FALTA UN PROCESO APARTE: la tarea programada se despierta cada 2
horas, trabaja y se cierra. Entre pasada y pasada no hay nadie leyendo, asi que
un comando escrito a las 10:15 no lo veria nadie hasta las 12:00. Este modo
(--escucha) es lo unico que esta permanentemente atento.

SEGURIDAD: solo se atienden comandos de los chats autorizados. El token del bot
puede acabar en manos de cualquiera y sin este filtro un desconocido podria
lanzar pasadas contra Rentway.
"""
import os
import time
import json
import urllib.request
import urllib.parse

ESPERA = 50          # segundos que Telegram mantiene la conexion abierta
API = "https://api.telegram.org/bot%s/getUpdates"


def chats_autorizados(base, chat_configurado):
    """El chat configurado en el programa, mas los que se listen (uno por linea)
    en 'chats_autorizados.txt' junto al .exe.

    Sirve para poder mandar comandos tambien desde el chat privado con el bot
    cuando lo configurado es el grupo, sin tener que cambiar la configuracion.
    """
    ids = {str(chat_configurado).strip()}
    f = os.path.join(base, "chats_autorizados.txt")
    if os.path.exists(f):
        try:
            with open(f, encoding="utf-8-sig") as h:      # utf-8-sig: quita el BOM
                for linea in h:
                    linea = linea.split("#")[0].strip()
                    if linea:
                        ids.add(linea)
        except Exception:
            pass
    return ids


def _pedir(token, datos, timeout):
    url = API % token
    cuerpo = urllib.parse.urlencode(datos).encode("utf-8")
    with urllib.request.urlopen(url, data=cuerpo, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _descartar_atrasados(token, log):
    """Al arrancar, ignora lo que se escribio mientras el programa estaba parado.

    Sin esto, si alguien escribio /revisar el viernes por la tarde, el lunes al
    encender se ejecutaria de golpe: Telegram guarda los mensajes 24 h.
    """
    try:
        r = _pedir(token, {"timeout": 0, "offset": -1}, timeout=20)
        res = r.get("result") or []
        if res:
            log("  descarto los comandos anteriores al arranque")
            return res[-1]["update_id"] + 1
    except Exception:
        pass
    return None


def bucle(token, autorizados, atender, log=print, parar=None, responder=None):
    """Escucha hasta que se pida parar.

    atender(cmd, args, chat_id) -> texto de respuesta inmediata (o None).
    responder(chat_id, texto)   -> como contestar (normalmente avisos.enviar).
    """
    offset = _descartar_atrasados(token, log)
    fallos = 0
    log("Escuchando comandos de Telegram (chats autorizados: %s)" % ", ".join(sorted(autorizados)))

    def dormir(s):
        if parar:
            parar.wait(s)
        else:
            time.sleep(s)

    while not (parar and parar.is_set()):
        try:
            datos = {"timeout": ESPERA, "allowed_updates": json.dumps(["message"])}
            if offset is not None:
                datos["offset"] = offset
            # el timeout de HTTP tiene que ser MAYOR que el de Telegram, si no
            # se corta la conexion justo antes de que el servidor conteste
            r = _pedir(token, datos, timeout=ESPERA + 20)
            fallos = 0
        except Exception as e:
            fallos += 1
            txt = str(e)
            if "409" in txt:
                # otro proceso esta leyendo el mismo bot: Telegram solo deja uno
                log("  ATENCION: otro proceso esta escuchando este bot (409). "
                    "Debe haber UNA sola escucha o ninguno recibe los comandos.")
                dormir(60)
            else:
                espera = min(300, 5 * fallos)
                log("  sin conexion con Telegram (%s). Reintento en %d s" % (txt[:80], espera))
                dormir(espera)
            continue

        for u in r.get("result", []):
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            texto = (msg.get("text") or "").strip()
            chat_id = str((msg.get("chat") or {}).get("id", ""))
            if not texto.startswith("/"):
                continue
            if chat_id not in autorizados:
                log("  comando '%s' IGNORADO: chat %s no autorizado" % (texto[:20], chat_id))
                continue

            partes = texto.split()
            # '/revisar@DagFlotaBot' en grupos lleva el nombre del bot pegado
            cmd = partes[0].lstrip("/").split("@")[0].lower()
            args = partes[1:]
            quien = (msg.get("from") or {}).get("first_name", "?")
            log("  comando /%s de %s (chat %s)" % (cmd, quien, chat_id))
            try:
                respuesta = atender(cmd, args, chat_id)
            except Exception as e:
                respuesta = "No he podido ejecutarlo: %s" % str(e)[:150]
                log("  fallo atendiendo /%s: %s" % (cmd, str(e)[:150]))
            if respuesta and responder:
                responder(chat_id, respuesta)
