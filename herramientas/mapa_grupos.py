# -*- coding: utf-8 -*-
"""
Genera src/grupos.json: {codigo de grupo: descripcion}, p.ej. "SC": "Economic 4".

Rentway no trae la descripcion del grupo en el informe de reservas (2126), solo
el codigo ("ID de grupo"). Donde si esta es en el 2162 "Informacion de
Reserva", columna "Tarifa" (el nombre engaña: es la descripcion del grupo). Se
cruzan por N.º Reserva usando tambien el 2119, que mira 60 dias atras y cubre
mas grupos.

El 17/09/2026 el cruce dio 30+ grupos y NINGUNA contradiccion (cada codigo con
una sola descripcion). Si algun dia aparece una, se queda la mas frecuente y se
avisa por pantalla.

Uso (en el servidor, con los informes de la ultima pasada en Downloads):
    sudo -u oneways /opt/oneways/venv/bin/python herramientas/mapa_grupos.py \
        /home/oneways/Downloads src/grupos.json
"""
import sys, os, glob, json, collections

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import avis_monitor as am   # noqa: E402


def ultimo(carpeta, patron):
    fs = glob.glob(os.path.join(carpeta, patron))
    return max(fs, key=os.path.getmtime) if fs else None


def main(carpeta, salida):
    info = ultimo(carpeta, am.PATRONES_EXCEL["contacto_res"])
    if not info:
        sys.exit("No encuentro reservation_information_*.xlsx en %s" % carpeta)
    i2, d2 = am._leer_hoja(info)
    tarifa = {am._norm(am._col(i2, r, "N.º Reserva")): am._norm(am._col(i2, r, "Tarifa"))
              for r in d2}

    votos = collections.defaultdict(collections.Counter)
    for clave in ("reservas", "detalle"):
        f = ultimo(carpeta, am.PATRONES_EXCEL[clave])
        if not f:
            continue
        idx, data = am._leer_hoja(f)
        for r in data:
            cod = am._norm(am._col(idx, r, "ID de grupo"))
            desc = tarifa.get(am._norm(am._col(idx, r, "N.º Reserva")))
            if cod and desc:
                votos[cod][desc] += 1

    mapa = {}
    for cod, cont in sorted(votos.items()):
        mapa[cod] = cont.most_common(1)[0][0]
        if len(cont) > 1:
            print("OJO: %s tiene varias descripciones: %s" % (cod, dict(cont)))
    with open(salida, "w", encoding="utf-8") as f:
        json.dump(mapa, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("%d grupos -> %s" % (len(mapa), salida))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Downloads"),
         sys.argv[2] if len(sys.argv) > 2 else "grupos.json")
