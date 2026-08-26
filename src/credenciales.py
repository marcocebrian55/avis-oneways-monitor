# -*- coding: utf-8 -*-
"""
Guarda las credenciales de Rentway CIFRADAS con DPAPI de Windows.

DPAPI ata el cifrado a ESTE usuario y ESTE equipo: el fichero resultante no
sirve de nada si alguien se lo lleva a otro ordenador. Por eso la contraseña no
va nunca dentro del .exe.

Esa misma propiedad impide mover una instalacion de un equipo a otro, asi que
al final del fichero hay un importador de 'configuracion.json': un fichero
PORTABLE con los datos en claro que se vuelca a este almacen en el primer
arranque. Quien tenga ese fichero tiene las claves.
"""
import os, json, base64, stat

ES_WINDOWS = (os.name == "nt")

if ES_WINDOWS:
    import ctypes
    from ctypes import wintypes
else:                                  # en Linux no existe ninguna de las dos
    ctypes = wintypes = None


if ES_WINDOWS:
    # ---------------- Windows: DPAPI ----------------
    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _a_blob(datos):
        buf = ctypes.create_string_buffer(datos, len(datos))
        return _BLOB(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _de_blob(blob):
        n = int(blob.cbData)
        out = ctypes.create_string_buffer(n)
        ctypes.memmove(out, blob.pbData, n)
        ctypes.windll.kernel32.LocalFree(blob.pbData)
        return out.raw

    def cifrar(texto):
        ent = _a_blob(b"AvisOneways")
        dentro = _a_blob(texto.encode("utf-8"))
        fuera = _BLOB()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(dentro), u"AvisOneways", ctypes.byref(ent),
            None, None, 0, ctypes.byref(fuera))
        if not ok:
            raise OSError("CryptProtectData fallo")
        return base64.b64encode(_de_blob(fuera)).decode("ascii")

    def descifrar(texto_b64):
        ent = _a_blob(b"AvisOneways")
        datos = base64.b64decode(texto_b64.encode("ascii"))
        dentro = _a_blob(datos)
        fuera = _BLOB()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(dentro), None, ctypes.byref(ent),
            None, None, 0, ctypes.byref(fuera))
        if not ok:
            raise OSError("CryptUnprotectData fallo (¿fichero de otro equipo o usuario?)")
        return _de_blob(fuera).decode("utf-8")

else:
    # ---------------- Linux/servidor: permisos de fichero ----------------
    #
    # NO SE LLAMA CIFRADO A PROPOSITO. DPAPI funciona porque Windows guarda la
    # clave maestra en el perfil del usuario y no la deja salir del equipo. En
    # un servidor no hay equivalente: cualquier clave que pusieramos aqui
    # tendria que estar en el disco, al lado del dato, y quien pueda leer una
    # puede leer la otra. Un XOR casero no anadiria seguridad, solo la
    # apariencia de tenerla, que es peor porque invita a bajar la guardia.
    #
    # Lo que de verdad protege el fichero es el modo 0600 y que el servicio
    # corra con su propio usuario, igual que una clave SSH o un
    # EnvironmentFile de systemd. El base64 solo evita que las claves salten a
    # la vista de quien mire por encima del hombro o haga un `grep` distraido.
    def cifrar(texto):
        return "b64:" + base64.b64encode(texto.encode("utf-8")).decode("ascii")

    def descifrar(texto):
        if texto.startswith("b64:"):
            return base64.b64decode(texto[4:].encode("ascii")).decode("utf-8")
        # Un .dat traido de un Windows: DPAPI ata el cifrado a aquel equipo, asi
        # que aqui es ilegible. Se dice claramente en vez de devolver basura.
        raise OSError("Este .dat viene de un Windows (DPAPI) y no se puede leer "
                      "en este servidor. Vuelve a poner las credenciales aqui, "
                      "o usa variables de entorno.")


def _proteger(ruta_fichero):
    """Deja el fichero en 0600 (solo su dueno). En Windows no hace nada: alli
    lo que protege es DPAPI, que ata el contenido al usuario y al equipo."""
    if ES_WINDOWS:
        return
    try:
        os.chmod(ruta_fichero, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass


def ruta(base):
    return os.path.join(base, "credenciales.dat")


def guardar(base, usuario, clave):
    with open(ruta(base), "w", encoding="utf-8") as f:
        json.dump({"usuario": cifrar(usuario), "clave": cifrar(clave)}, f)
    _proteger(ruta(base))


def cargar(base):
    """Devuelve (usuario, clave) o (None, None) si no hay o no se puede leer.

    El entorno MANDA sobre el fichero. Es lo que permite que el servicio de
    systemd reciba las claves por EnvironmentFile sin dejar ningun .dat en el
    disco de la aplicacion, y que un contenedor se configure sin tocar nada."""
    env_u = os.environ.get("RENTWAY_USUARIO")
    env_c = os.environ.get("RENTWAY_CLAVE")
    if env_u and env_c:
        return env_u, env_c
    p = ruta(base)
    if not os.path.exists(p):
        return None, None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return descifrar(d["usuario"]), descifrar(d["clave"])
    except Exception:
        return None, None


def hay(base):
    return os.path.exists(ruta(base))


# ---------- Telegram (token y chat_id, tambien cifrados) ----------
def ruta_telegram(base):
    return os.path.join(base, "telegram.dat")


def guardar_telegram(base, token, chat_id):
    """El token da control TOTAL del bot a quien lo tenga: se cifra igual."""
    with open(ruta_telegram(base), "w", encoding="utf-8") as f:
        json.dump({"token": cifrar(token), "chat": cifrar(str(chat_id))}, f)
    _proteger(ruta_telegram(base))


def cargar_telegram(base):
    env_t = os.environ.get("TELEGRAM_TOKEN")
    env_c = os.environ.get("TELEGRAM_CHAT")
    if env_t and env_c:
        return env_t, env_c
    p = ruta_telegram(base)
    if not os.path.exists(p):
        return None, None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return descifrar(d["token"]), descifrar(d["chat"])
    except Exception:
        return None, None


# ---------- Correo (SMTP). Solo la clave se cifra; el resto es config ----------
def ruta_correo(base):
    return os.path.join(base, "correo.dat")


def guardar_correo(base, servidor, puerto, usuario, clave, destinatarios,
                   remitente="", avisos_fallo=None):
    """`remitente` es opcional: sirve para que el aviso salga DESDE otra
    direccion distinta de la que se usa para autenticarse.

    Caso real: un buzon compartido/delegado (aucc.rentway@...) no tiene
    contraseña propia, asi que hay que entrar con la cuenta personal pero firmar
    con la del buzon. Para que Gmail lo acepte, esa direccion debe estar dada de
    alta en "Enviar como" de la cuenta que se autentica; si no, la reescribe.

    `avisos_fallo` es la direccion a la que van los AVISOS DE ERROR, que NO son
    los mismos destinatarios que los avisos de oneways: un error lo arregla
    quien mantiene el sistema, no las oficinas.

    OJO, `avisos_fallo=None` significa "deja el que ya hubiera". Hace falta
    porque la ventana de Windows llama aqui para guardar SOLO
    la lista de destinatarios, sin saber de este campo; con un "" por defecto
    lo borrarian sin querer cada vez que alguien toca la lista."""
    if avisos_fallo is None:
        avisos_fallo = (cargar_correo(base) or {}).get("avisos_fallo", "")
    with open(ruta_correo(base), "w", encoding="utf-8") as f:
        json.dump({"servidor": servidor, "puerto": str(puerto), "usuario": usuario,
                   "clave": cifrar(clave), "destinatarios": destinatarios,
                   "remitente": remitente, "avisos_fallo": avisos_fallo}, f,
                  ensure_ascii=False)
    _proteger(ruta_correo(base))


def cargar_correo(base):
    """Devuelve dict con la config o None."""
    p = ruta_correo(base)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        d["clave"] = descifrar(d["clave"])
        d.setdefault("remitente", "")     # config guardada antes de existir el campo
        d.setdefault("avisos_fallo", "")  # idem
        return d
    except Exception:
        return None


# ---------- Configuracion PORTABLE (llevar la herramienta a otro equipo) ----------
# DPAPI ata los .dat a un equipo+usuario concretos, asi que copiarlos NO sirve:
# en el equipo nuevo CryptUnprotectData falla. Para poder clonar el repositorio y
# arrancar sin reescribir nada a mano existe 'configuracion.json', que lleva los
# datos en claro y se vuelca al almacen cifrado LOCAL en el primer arranque.
NOMBRE_CONFIG = "configuracion.json"


def ruta_config(base):
    """Busca configuracion.json junto al programa y, si no, un nivel por encima.

    El segundo sitio hace falta al correr desde el repositorio: ahi el programa
    vive en src/ pero el fichero esta en la raiz del clon."""
    for d in (base, os.path.dirname(os.path.abspath(base))):
        p = os.path.join(d, NOMBRE_CONFIG)
        if os.path.exists(p):
            return p
    return None


def _toca_importar(destino, origen):
    """Importa si aun no hay .dat o si el JSON es mas nuevo que el.

    Asi el JSON manda tras un `git pull`, pero lo que se cambie luego en la
    ventana de Configuracion no se pisa en el siguiente arranque."""
    if not os.path.exists(destino):
        return True
    return os.path.getmtime(origen) > os.path.getmtime(destino)


def importar_configuracion(base):
    """Vuelca configuracion.json al almacen cifrado. Devuelve lo que importo."""
    p = ruta_config(base)
    if not p:
        return []
    # utf-8-sig: este fichero lo edita gente a mano y el Bloc de notas le mete
    # un BOM invisible que rompe json.load
    with open(p, encoding="utf-8-sig") as f:
        cfg = json.load(f)

    hecho = []
    r = cfg.get("rentway") or {}
    if r.get("usuario") and _toca_importar(ruta(base), p):
        guardar(base, r["usuario"], r.get("clave", ""))
        hecho.append("credenciales de Rentway")

    t = cfg.get("telegram") or {}
    if t.get("token") and _toca_importar(ruta_telegram(base), p):
        guardar_telegram(base, t["token"], t.get("chat", ""))
        hecho.append("Telegram")

    c = cfg.get("correo") or {}
    if c.get("usuario") and _toca_importar(ruta_correo(base), p):
        guardar_correo(base, c.get("servidor", "smtp.gmail.com"),
                       c.get("puerto", "465"), c["usuario"], c.get("clave", ""),
                       c.get("destinatarios", ""), c.get("remitente", ""),
                       c.get("avisos_fallo", ""))
        hecho.append("correo")
    return hecho
