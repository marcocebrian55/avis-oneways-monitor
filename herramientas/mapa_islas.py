# -*- coding: utf-8 -*-
"""Genera el mapa OFICINA -> ISLA a partir del catalogo de oficinas de Rentway.

DE DONDE SALE EL CATALOGO: Rentway > Configuraciones empresariales > Operaciones
> Oficina, boton de exportar. Da un Excel de dos columnas, Codigo y Descripcion.
La pantalla tiene ademas una columna "Zona", pero la rejilla es virtualizada
(DevExtreme) y solo existen en el DOM las filas visibles, asi que sacarla entera
por scraping cuesta mas de lo que aporta: con el Excel basta.

COMO DEDUCE LA ISLA, en dos pasadas:

  1. Por el NOMBRE. "Apt Tenerife Sur AVIS" se coloca solo. Resuelve unas 350
     de las 1920, casi todas oficinas de verdad; el resto son hoteles.

  2. Por el SITIO. Los codigos son [marca][sitio][numero de hotel]: la marca es
     A (AUCC), B (BCAR/Budget) o T (Turisprime), y el resto identifica el sitio.
     ACAS, BCAS y TCAS son el mismo sitio -- El Castillo, Fuerteventura -- y
     ACAS18 es un hotel de ahi. Asi que la isla de un hotel se hereda del sitio,
     que es MUCHO mas fiable que adivinar por el nombre del hotel: "Riu Paraiso"
     no dice donde esta, pero su prefijo APUC es "AUCC Puerto del Carmen".

Lo que no se resuelve se queda FUERA del mapa a proposito. Quien lo consuma debe
tratar una oficina desconocida como "mandaselo a todo el mundo y avisa", nunca
como "no se lo mandes a nadie": un hueco tiene que hacer ruido, no silencio.
"""
import collections
import json
import os
import sys
import unicodedata

ISLAS = ("Fuerteventura", "Lanzarote", "Gran Canaria", "Tenerife",
         "La Palma", "El Hierro", "La Gomera")

# Topónimos que identifican la isla sin lugar a dudas. Van sin acentos porque
# la descripcion se normaliza antes de comparar: en el Excel conviven
# "Playa del Ingles" y "Playa del Inglés", y XSAG se quedaba sin isla por eso.
CLAVES = {
    "Fuerteventura": ["fuerteventura", "fuertev", " fue", "jandia", "corralejo",
                      "costa calma", "morro jable", "pajara", "caleta de fuste",
                      "el castillo", "tarajalejo"],
    "Lanzarote":     ["lanzarote", "arrecife", "playa blanca", "puerto del carmen",
                      "costa teguise", "rubicon", "yaiza", "tias"],
    "Gran Canaria":  ["gran canaria", "gc ", "las palmas", "maspalomas",
                      "playa del ingles", "puerto rico", "meloneras", "mogan",
                      "amadores", "arguineguin", "taurito", "san agustin"],
    "Tenerife":      ["tenerife", "santa cruz", "adeje", "americas", "arona",
                      "puerto de la cruz", "cristianos", "los gigantes"],
    "La Palma":      ["la palma"],
    "El Hierro":     ["hierro"],
    "La Gomera":     ["gomera"],
}


def sin_acentos(s):
    d = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in d if unicodedata.category(c) != "Mn").lower()


def por_nombre(descripcion):
    t = sin_acentos(descripcion)
    # "Las Palmas" primero: si no, "la palma" lo captura y manda los oneways de
    # Gran Canaria a La Palma. Un fallo de una letra que no se veria nunca.
    if "las palmas" in t:
        return "Gran Canaria"
    for isla, claves in CLAVES.items():
        for k in claves:
            if k in t:
                return isla
    return None


def sitio(codigo):
    """[marca][sitio][numero] -> el sitio. ACAS18 y BCAS01 -> CAS."""
    s = str(codigo)
    if len(s) > 1 and s[0] in "ABT":
        s = s[1:]
    while s and s[-1].isdigit():
        s = s[:-1]
    return s or str(codigo)


def construir(oficinas):
    """oficinas: {codigo: descripcion} -> ({codigo: isla}, [codigos sin isla])"""
    isla = {c: por_nombre(d) for c, d in oficinas.items()}

    votos = collections.defaultdict(collections.Counter)
    for c, v in isla.items():
        if v:
            votos[sitio(c)][v] += 1

    por_sitio = {}
    for s, cuenta in votos.items():
        arriba, n = cuenta.most_common(1)[0]
        # Se exige consenso: un sitio con las islas repartidas significa que el
        # patron no aplica ahi, y entonces es mejor no saber que saber mal.
        if n / float(sum(cuenta.values())) >= 0.8:
            por_sitio[s] = arriba

    for c in isla:
        if not isla[c]:
            isla[c] = por_sitio.get(sitio(c))

    mapa = {c: v for c, v in isla.items() if v}
    sin = sorted(c for c, v in isla.items() if not v)
    return mapa, sin


def leer_excel(ruta):
    from openpyxl import load_workbook
    wb = load_workbook(ruta, read_only=True, data_only=True)
    out = {}
    for cod, des in wb.active.iter_rows(min_row=2, values_only=True):
        if cod and des:
            out[str(cod).strip()] = str(des).strip()
    wb.close()
    return out


def main():
    if len(sys.argv) < 2:
        print("uso: mapa_islas.py <oficinas.xlsx> [salida.json]")
        return 2
    oficinas = leer_excel(sys.argv[1])
    mapa, sin = construir(oficinas)
    destino = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "src", "oficinas_islas.json")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(mapa, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("oficinas en el catalogo : %d" % len(oficinas))
    print("con isla                : %d (%.1f%%)" % (len(mapa), 100.0 * len(mapa) / len(oficinas)))
    print("sin isla                : %d" % len(sin))
    print("reparto                 : %s" % dict(collections.Counter(mapa.values()).most_common()))
    print("escrito                 : %s" % os.path.normpath(destino))
    if sin:
        print("sin resolver (van al cajon de 'todos'): %s" % ", ".join(sin[:20]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
