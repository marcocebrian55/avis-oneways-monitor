# -*- coding: utf-8 -*-
"""Resumen de una noche de pasadas, centrado en el informe de Abiertos.

POR QUE EXISTE: el 25/08/2026 el informe de Abiertos (contratos) se colgo con
Timeout en CINCO pasadas seguidas de madrugada (00:00 a 07:00) y funciono bien
a partir de las 08:00. Solo quedo constancia en el log, que a las 04:00 no lee
nadie.

El aviso de fallo dice QUE ha pasado. Esto cuenta el PATRON, que es lo que hace
falta para saber si es una franja horaria concreta, una casualidad o algo que va
a peor. Sin el patron no se puede decidir si la solucion es subir el timeout,
mover las pasadas de hora o reclamar a Rentway.

Va a la direccion de avisos de fallo, NUNCA a las oficinas: es material de
diagnostico, no un aviso accionable por un mostrador.

ES TEMPORAL. En cuanto se entienda el atasco, este resumen y su timer sobran:
borrar oneways-resumen.timer y este fichero.
"""
import os, sys, datetime

BASE = os.environ.get("ONEWAYS_DATOS") or os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERDE, ROJO, AMBAR = "#0a7d00", "#b00000", "#b06a00"


def leer_pasadas(ruta_log, dia):
    """Saca una ficha por pasada del dia pedido. Sin regex a proposito: el log
    tiene formato fijo 'YYYY-MM-DD HH:MM:SS ' y trocear por posicion no se
    rompe cuando el mensaje lleva corchetes."""
    pasadas, actual = [], None
    with open(ruta_log, encoding="utf-8", errors="replace") as f:
        for linea in f:
            if len(linea) < 20 or linea[:10] != dia:
                continue
            hora, resto = linea[11:19], linea[20:].rstrip()

            if "=== PASADA TERMINADA ===" in resto:
                if actual:
                    actual["fin"] = hora
                    pasadas.append(actual)
                    actual = None
                continue

            if resto.startswith("=== PASADA ["):
                origen = resto.split("[", 1)[1].split("]", 1)[0]
                actual = {"inicio": hora, "fin": None, "origen": origen,
                          "ok": False, "fallos": 0, "sin_informe": False,
                          "fichero": None}
                continue

            if actual is None:
                continue
            if "[Abiertos] descargado:" in resto:
                actual["ok"] = True
                actual["fichero"] = resto.split("descargado:", 1)[1].strip()
            elif "[Abiertos] intento" in resto and "fallido" in resto:
                actual["fallos"] += 1
            elif "SIN el informe de Abiertos" in resto:
                actual["sin_informe"] = True

    if actual:                      # pasada aun en curso al generar el resumen
        pasadas.append(actual)
    return pasadas


def _segundos(hhmmss):
    h, m, s = (int(x) for x in hhmmss.split(":"))
    return h * 3600 + m * 60 + s


def cuerpo(dia, pasadas):
    malas = [p for p in pasadas if not p["ok"]]
    filas = []
    for p in pasadas:
        if p["ok"] and not p["fallos"]:
            color, estado = VERDE, "OK"
        elif p["ok"]:
            color, estado = AMBAR, "OK al reintento %d" % (p["fallos"] + 1)
        else:
            color, estado = ROJO, "FALLO (%d intentos)" % p["fallos"]
        dur = ""
        if p["fin"]:
            dur = "%d min %02d s" % divmod(_segundos(p["fin"]) - _segundos(p["inicio"]), 60)
        filas.append(
            "<tr>"
            "<td style='padding:6px 10px;border-bottom:1px solid #eee'><b>%s</b></td>"
            "<td style='padding:6px 10px;border-bottom:1px solid #eee;color:#666'>%s</td>"
            "<td style='padding:6px 10px;border-bottom:1px solid #eee;color:%s'><b>%s</b></td>"
            "<td style='padding:6px 10px;border-bottom:1px solid #eee;color:#666'>%s</td>"
            "</tr>" % (p["inicio"], p["origen"], color, estado, dur))

    if not pasadas:
        veredicto = "No hay ninguna pasada registrada en el log para este dia. Eso ya es un problema."
        color = ROJO
    elif not malas:
        veredicto = ("El informe de Abiertos bajo bien en las %d pasadas. "
                     "Anoche no se repitio." % len(pasadas))
        color = VERDE
    else:
        horas = ", ".join(p["inicio"][:5] for p in malas)
        veredicto = ("El informe de Abiertos FALLO en %d de %d pasadas: %s. "
                     "En esas pasadas los oneways de contratos se compararon contra "
                     "el open_*.xlsx de una pasada anterior, o sea contra datos viejos."
                     % (len(malas), len(pasadas), horas))
        color = ROJO

    return ("<html><body style='font-family:Segoe UI,Arial,sans-serif;color:#222'>"
            "<div style='border-top:4px solid #D4002B;padding-top:10px;max-width:680px'>"
            "<div style='font-size:18px;font-weight:bold;color:#D4002B'>AVIS &middot; Monitor de Oneways</div>"
            "<div style='color:#666;font-size:13px;margin-bottom:12px'>Resumen del informe de Abiertos &mdash; %s</div>"
            "<div style='padding:10px 12px;background:#FAFAFB;border-left:4px solid %s;font-size:14px'>%s</div>"
            "<table style='border-collapse:collapse;width:100%%;margin-top:14px;font-size:13px'>"
            "<tr style='color:#666;text-align:left'>"
            "<th style='padding:6px 10px'>Pasada</th><th style='padding:6px 10px'>Origen</th>"
            "<th style='padding:6px 10px'>Abiertos</th><th style='padding:6px 10px'>Duracion</th></tr>"
            "%s</table>"
            "<div style='color:#888;font-size:11px;margin-top:16px;border-top:1px solid #eee;padding-top:8px'>"
            "Correo de DIAGNOSTICO, temporal, mientras se investiga por que ese informe se "
            "cuelga de madrugada. Solo va a quien mantiene el sistema. Para quitarlo: "
            "systemctl disable --now oneways-resumen.timer</div>"
            "</div></body></html>" % (dia, color, veredicto, "".join(filas)))


def main():
    dia = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
    ruta_log = os.path.join(BASE, "avis_oneways.log")
    if not os.path.exists(ruta_log):
        print("No encuentro el log en", ruta_log)
        return 1

    pasadas = leer_pasadas(ruta_log, dia)
    malas = [p for p in pasadas if not p["ok"]]
    for p in pasadas:
        print("%s [%s] Abiertos=%s fallos=%d" % (p["inicio"], p["origen"],
                                                 "OK" if p["ok"] else "FALLO", p["fallos"]))
    print("-> %d pasadas, %d sin el informe" % (len(pasadas), len(malas)))

    import credenciales, correo
    cfg = credenciales.cargar_correo(BASE)
    destino = (cfg or {}).get("avisos_fallo", "")
    if not cfg or not destino:
        print("Sin direccion de avisos de fallo configurada: no mando nada.")
        return 1

    marca = "%s Abiertos: %s" % (("\u26a0\ufe0f" if malas else "\u2705"),
                                 ("fallo en %d de %d pasadas" % (len(malas), len(pasadas))
                                  if malas else "bien en las %d pasadas" % len(pasadas)))
    ok = correo.enviar(cfg["servidor"], cfg["puerto"], cfg["usuario"], cfg["clave"],
                       destino, "%s (%s)" % (marca, dia), cuerpo(dia, pasadas),
                       remitente=cfg.get("remitente") or None, log=print)
    print("Resumen enviado a %s: %s" % (destino, "SI" if ok else "NO"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
