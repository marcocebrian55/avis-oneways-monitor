# -*- coding: utf-8 -*-
"""
Arma el paquete de entrega y el manifiesto de actualizacion.

Genera en 'release/':
  AvisMonitorOneways.exe   el binario suelto -> es lo que baja el AUTO-ACTUALIZADOR
                           (actualizacion.descargar() espera un .exe, no un zip)
  AvisMonitorOneways.zip   paquete completo (exe + navegador + instalador) para
                           una instalacion NUEVA
  version.json             manifiesto: version, url del .exe y su sha256

EL ZIP SE GENERA CON zipfile A PROPOSITO: Compress-Archive y ZipFile::CreateFromDirectory
de PowerShell 5.1 escriben las rutas internas con BARRA INVERTIDA, y hay
descompresores que entonces dejan los ficheros sueltos con la ruta metida en el
nombre -> instalacion rota sin explicacion.
"""
import os, re, sys, json, shutil, hashlib, zipfile

RAIZ = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(RAIZ, "dist")
SALIDA = os.path.join(RAIZ, "release")
NAVEGADOR = os.path.join(os.environ["LOCALAPPDATA"], "ms-playwright")
# El navegador que espera ESTE playwright. Empaquetar otro (p.ej. el 1228 de la
# herramienta de extraccion de RMS) da "Executable doesn't exist" al arrancar.
CHROMIUM = "chromium-1223"
EXTRA_NAVEGADOR = ["winldd-1007"]

REPO = "marcocebrian55/avis-monitor-oneways"


def version_del_codigo():
    t = open(os.path.join(RAIZ, "src", "avis_monitor.py"), encoding="utf-8").read()
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', t, re.M)
    if not m:
        sys.exit("No encuentro VERSION en src/avis_monitor.py")
    return m.group(1)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


def main():
    ver = version_del_codigo()
    exe = os.path.join(DIST, "AvisMonitorOneways.exe")
    if not os.path.exists(exe):
        sys.exit("No existe dist/AvisMonitorOneways.exe: compila primero")

    # COMPROBACION DE COHERENCIA: el .exe tiene que llevar dentro la MISMA
    # version que el codigo. Publicar un numero que no coincide con el binario
    # deja a todos los equipos actualizandose EN BUCLE en cada pasada.
    #
    # Se le pregunta al propio binario con --version. No vale buscar la cadena
    # dentro del .exe: en un --onefile el codigo va comprimido y no aparece.
    import subprocess
    marca = os.path.join(DIST, "version_actual.txt")
    if os.path.exists(marca):
        os.remove(marca)
    subprocess.run([exe, "--version"], capture_output=True, timeout=120)
    if not os.path.exists(marca):
        sys.exit("El .exe no responde a --version: ¿es un binario anterior a este cambio?")
    con = open(marca, encoding="utf-8").read().strip()
    os.remove(marca)
    if con != ver:
        sys.exit("DESCUADRE: el codigo dice %s y el .exe dice %s. Recompila." % (ver, con))
    print("version:", ver, "(confirmada por el propio binario)")

    if os.path.exists(SALIDA):
        shutil.rmtree(SALIDA)
    os.makedirs(SALIDA)

    # --- 1. el .exe suelto, para el auto-actualizador ---
    shutil.copy2(exe, os.path.join(SALIDA, "AvisMonitorOneways.exe"))

    # --- 2. carpeta de entrega -> zip ---
    tmp = os.path.join(SALIDA, "_paquete")
    os.makedirs(tmp)
    shutil.copy2(exe, os.path.join(tmp, "AvisMonitorOneways.exe"))
    for f in os.listdir(os.path.join(RAIZ, "instalador")):
        shutil.copy2(os.path.join(RAIZ, "instalador", f), os.path.join(tmp, f))
    shutil.copy2(os.path.join(RAIZ, "docs", "LEEME - INSTALACION.txt"),
                 os.path.join(tmp, "LEEME.txt"))
    shutil.copy2(os.path.join(RAIZ, "docs", "PASOS RAPIDOS.txt"),
                 os.path.join(tmp, "PASOS RAPIDOS.txt"))

    destino_nav = os.path.join(tmp, "ms-playwright")
    os.makedirs(destino_nav)
    for d in [CHROMIUM] + EXTRA_NAVEGADOR:
        o = os.path.join(NAVEGADOR, d)
        if not os.path.isdir(o):
            sys.exit("Falta el navegador %s en %s" % (d, NAVEGADOR))
        shutil.copytree(o, os.path.join(destino_nav, d))
    # .links lo usa playwright para localizar los navegadores
    enlaces = os.path.join(NAVEGADOR, ".links")
    if os.path.isdir(enlaces):
        shutil.copytree(enlaces, os.path.join(destino_nav, ".links"))

    zip_path = os.path.join(SALIDA, "AvisMonitorOneways.zip")
    n = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for base, _, ficheros in os.walk(tmp):
            for f in ficheros:
                completo = os.path.join(base, f)
                interno = os.path.relpath(completo, tmp).replace("\\", "/")
                z.write(completo, interno)
                n += 1
    shutil.rmtree(tmp)
    print("zip: %d ficheros, %.1f MB" % (n, os.path.getsize(zip_path) / 1e6))

    # --- 3. manifiesto ---
    # La url apunta al .EXE (no al zip): el actualizador sustituye el binario.
    manifiesto = {
        "version": ver,
        "url": "https://github.com/%s/releases/download/v%s/AvisMonitorOneways.exe" % (REPO, ver),
        "sha256": sha256(os.path.join(SALIDA, "AvisMonitorOneways.exe")),
        "notas": "El aviso por correo ahora es solo de oneways NUEVOS. "
                 "Por Telegram siguen llegando todos los cambios.",
        "obligatoria": False,
    }
    # sin BOM: el lector usa utf-8-sig, pero otros consumidores no tienen por que
    with open(os.path.join(SALIDA, "version.json"), "w", encoding="utf-8") as f:
        json.dump(manifiesto, f, ensure_ascii=False, indent=2)

    print("exe :  %.1f MB" % (os.path.getsize(exe) / 1e6))
    print("sha256:", manifiesto["sha256"][:32], "...")
    print("listo en", SALIDA)


if __name__ == "__main__":
    main()
