# -*- coding: utf-8 -*-
"""
Actualizaciones: TÚ publicas, los demás reciben.

Cómo funciona
-------------
1. Publicas un fichero `version.json` en un sitio accesible (carpeta de OneDrive
   compartida hoy; GitHub Releases mañana: solo cambia la URL) con la forma:

       {
         "version": "1.1.0",
         "url": "https://.../AvisMonitorOneways.exe",
         "sha256": "….",                (opcional pero MUY recomendable)
         "notas": "Qué cambia en esta versión",
         "obligatoria": false
       }

2. Cada programa comprueba ese fichero al abrirse y en cada pasada automática.
3. Si hay una versión mayor, avisa. Si se acepta (o si es obligatoria), se
   descarga al lado del .exe como `pendiente.exe`.
4. Al ARRANCAR, si hay un `pendiente.exe`, se hace el cambio y se relanza.

Por qué se cambia al arrancar y no en caliente: en Windows un .exe NO puede
sobrescribirse a sí mismo mientras corre. Sí se puede RENOMBRAR, y de ahí el
truco: se renombra el actual, se pone el nuevo en su sitio y se relanza.

SEGURIDAD: esto descarga y ejecuta código. Solo por HTTPS, y si el manifiesto
trae `sha256` se verifica; si no cuadra, se descarta el fichero.
"""
import os, sys, json, time, hashlib, subprocess
import urllib.request

VERSION = "1.1.0"
TIEMPO = 25
NOMBRE_PENDIENTE = "pendiente.exe"


def _num(v):
    """'1.10.2' -> (1,10,2) para poder comparar de verdad (1.10 > 1.9)."""
    out = []
    for parte in str(v).split("."):
        try:
            out.append(int("".join(c for c in parte if c.isdigit()) or 0))
        except Exception:
            out.append(0)
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])


def hay_novedad(remota, local=VERSION):
    return _num(remota) > _num(local)


def consultar(url, log=None):
    """Lee el manifiesto. Devuelve dict o None (nunca lanza)."""
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=TIEMPO) as r:
            # utf-8-sig: PowerShell y el Bloc de notas meten un BOM invisible
            # al principio que rompe el analisis del JSON
            d = json.loads(r.read().decode("utf-8-sig"))
        if not d.get("version") or not d.get("url"):
            return None
        return d
    except Exception as e:
        if log:
            log("  No pude consultar actualizaciones: %s" % str(e)[:110])
        return None


def descargar(manifiesto, destino_dir, log=None):
    """Baja el .exe nuevo a 'pendiente.exe'. Devuelve True si quedo listo."""
    url = manifiesto.get("url", "")
    if not url.lower().startswith("https://") and not url.lower().startswith("file:"):
        if log:
            log("  Descarga rechazada: la URL no es HTTPS.")
        return False
    tmp = os.path.join(destino_dir, NOMBRE_PENDIENTE + ".parcial")
    final = os.path.join(destino_dir, NOMBRE_PENDIENTE)
    try:
        with urllib.request.urlopen(url, timeout=180) as r, open(tmp, "wb") as f:
            h = hashlib.sha256()
            while True:
                trozo = r.read(1 << 20)
                if not trozo:
                    break
                f.write(trozo)
                h.update(trozo)
        esperado = (manifiesto.get("sha256") or "").strip().lower()
        if esperado and h.hexdigest() != esperado:
            os.remove(tmp)
            if log:
                log("  Descarga DESCARTADA: el fichero no coincide con su huella.")
            return False
        if os.path.exists(final):
            os.remove(final)
        os.rename(tmp, final)
        if log:
            log("  Version %s descargada; se aplicara al reiniciar." % manifiesto.get("version"))
        return True
    except Exception as e:
        try:
            os.remove(tmp)
        except Exception:
            pass
        if log:
            log("  Fallo la descarga de la actualizacion: %s" % str(e)[:110])
        return False


def aplicar_si_toca(log=None):
    """Al arrancar: si hay 'pendiente.exe', ponerlo en su sitio y relanzar.

    Devuelve True si se ha relanzado (el programa debe cerrarse).
    """
    if not getattr(sys, "frozen", False):
        return False
    yo = sys.executable
    carpeta = os.path.dirname(yo)
    nuevo = os.path.join(carpeta, NOMBRE_PENDIENTE)
    if not os.path.exists(nuevo):
        _limpiar_viejos(carpeta)
        return False
    try:
        viejo = os.path.join(carpeta, "viejo_%s.exe" % time.strftime("%Y%m%d%H%M%S"))
        os.rename(yo, viejo)          # un .exe en marcha SI se puede renombrar
        os.rename(nuevo, yo)
        if log:
            log("Actualizacion aplicada. Relanzando...")
        subprocess.Popen([yo] + sys.argv[1:],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception as e:
        if log:
            log("No pude aplicar la actualizacion: %s" % str(e)[:110])
        return False


def _limpiar_viejos(carpeta):
    import glob
    for f in glob.glob(os.path.join(carpeta, "viejo_*.exe")):
        try:
            os.remove(f)
        except Exception:
            pass
