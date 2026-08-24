# -*- coding: utf-8 -*-
"""
Control de INSTANCIA ÚNICA entre equipos.

El monitor puede instalarse en varios portátiles, pero solo UNO debe estar
vigilando: si corren dos, se duplican los avisos y cada uno compara contra su
propio snapshot, con lo que ambos ven "cambios" falsos.

Mecanismo: un fichero de señal (`motor_activo.json`) en una carpeta COMPARTIDA
(OneDrive, unidad de red...). Quien está trabajando lo refresca cada minuto con
su equipo, su IP y la hora. Al arrancar, si la señal es de OTRO equipo y está
fresca, se avisa.

Si no se configura carpeta compartida, el control es solo local (evita dos
copias en el mismo PC, que ya es algo).
"""
import os, json, socket, getpass, datetime, threading, time

NOMBRE = "motor_activo.json"
FRESCA_MIN = 15          # una señal mas vieja que esto se considera abandonada
REFRESCO_SEG = 60

LOCK = "pasada_en_curso.lock"
LOCK_MAX_MIN = 45        # una pasada normal tarda minutos; mas que esto = colgada


def _ip_local():
    """IP con la que este equipo sale a la red (sin mandar nada)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "?"
    finally:
        s.close()


def yo():
    return {"equipo": socket.gethostname(), "ip": _ip_local(),
            "usuario": getpass.getuser(), "pid": os.getpid()}


def carpeta_por_defecto(base):
    """Dónde se deja la señal de "estoy vigilando".

    Para que sirva ENTRE EQUIPOS tiene que ser una carpeta que todos vean: una
    unidad de red o una ruta UNC (\\\\servidor\\carpeta). Se indica poniendo un
    fichero `senal.txt` junto al programa con esa ruta.

    Si no se configura, la señal es LOCAL: solo evita dos copias en el mismo PC.
    No pasa nada grave: el control de verdad es instalar la tarea programada en
    un unico equipo, y el instalador ya pregunta por ello.
    """
    f = os.path.join(base, "senal.txt")
    if os.path.exists(f):
        try:
            with open(f, encoding="utf-8-sig") as h:   # utf-8-sig: quita el BOM
                d = h.read().strip().lstrip("﻿").strip()
            if d:
                os.makedirs(d, exist_ok=True)
                return d
        except Exception:
            pass
    return base


def leer(carpeta):
    p = os.path.join(carpeta, NOMBRE)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def otra_instancia(carpeta):
    """Devuelve la señal de OTRO equipo si esta fresca; si no, None."""
    d = leer(carpeta)
    if not d:
        return None
    mio = yo()
    if d.get("equipo") == mio["equipo"] and d.get("usuario") == mio["usuario"]:
        return None                       # es nuestra propia señal
    try:
        t = datetime.datetime.fromisoformat(d.get("ultima_senal", ""))
    except Exception:
        return None
    edad = (datetime.datetime.now() - t).total_seconds() / 60.0
    if edad <= FRESCA_MIN:
        d["edad_min"] = round(edad, 1)
        return d
    return None


def escribir(carpeta):
    d = yo()
    d["ultima_senal"] = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        os.makedirs(carpeta, exist_ok=True)
        with open(os.path.join(carpeta, NOMBRE), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def soltar(carpeta):
    """Al cerrar, deja la señal vieja para que otro pueda tomar el relevo."""
    d = leer(carpeta)
    mio = yo()
    if d and d.get("equipo") == mio["equipo"] and d.get("usuario") == mio["usuario"]:
        try:
            os.remove(os.path.join(carpeta, NOMBRE))
        except Exception:
            pass


def _proceso_vivo(pid):
    """True si ese PID sigue existiendo en este equipo.

    Hay una version por sistema. En Linux la de Windows lanzaba AttributeError
    (`ctypes.windll` no existe) y caia en el `return True` de abajo, o sea que
    un candado huerfano NUNCA se detectaba: tras un cuelgue el programa se
    negaba a ejecutar pasadas hasta que el candado caducaba por edad (45 min).
    """
    try:
        pid = int(pid)
        if pid <= 0:
            return False
        if os.name == "nt":
            import ctypes
            SYNCHRONIZE = 0x00100000
            h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
            return False
        # POSIX: la senal 0 no hace nada, solo comprueba que el proceso existe.
        # EPERM significa que existe pero es de otro usuario -> tambien vive.
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    except Exception:
        return True          # ante la duda, suponer que vive (no pisar una pasada real)


def pasada_en_curso(base):
    """Devuelve los datos de la pasada que esta corriendo AHORA en este equipo,
    o None. Un candado viejo o de un proceso muerto se considera abandonado."""
    p = os.path.join(base, LOCK)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        edad = (datetime.datetime.now()
                - datetime.datetime.fromisoformat(d["inicio"])).total_seconds() / 60.0
    except Exception:
        return None
    if edad > LOCK_MAX_MIN or not _proceso_vivo(d.get("pid", 0)):
        try:
            os.remove(p)                  # candado huerfano: lo limpiamos
        except Exception:
            pass
        return None
    d["edad_min"] = round(edad, 1)
    return d


class BloqueoLocal:
    """Impide DOS pasadas a la vez en el mismo equipo.

    POR QUE: la tarea programada y el modo escucha (/revisar por Telegram) son
    procesos distintos, asi que el control de instancia entre equipos no los ve
    como rivales (mismo equipo y mismo usuario). Si coinciden, los dos abren
    Chromium sobre el MISMO perfil persistente y se corrompe.

    Se usa como 'with': si no puede tomarlo, self.tomado queda a False.
    """

    def __init__(self, base, quien="tarea"):
        self.base = base
        self.quien = quien
        self.tomado = False
        self.ocupado_por = None

    def __enter__(self):
        otra = pasada_en_curso(self.base)
        if otra:
            self.ocupado_por = otra
            return self
        try:
            with open(os.path.join(self.base, LOCK), "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "quien": self.quien,
                           "inicio": datetime.datetime.now().isoformat(timespec="seconds")},
                          f, ensure_ascii=False)
            self.tomado = True
        except Exception:
            self.tomado = True            # si no se puede escribir, no bloquear el trabajo
        return self

    def __exit__(self, *a):
        if not self.tomado:
            return False
        try:
            os.remove(os.path.join(self.base, LOCK))
        except Exception:
            pass
        return False


class Latido(threading.Thread):
    """Refresca la señal mientras el programa trabaja."""

    def __init__(self, carpeta):
        super().__init__(daemon=True)
        self.carpeta = carpeta
        self.parar = threading.Event()

    def run(self):
        while not self.parar.is_set():
            escribir(self.carpeta)
            self.parar.wait(REFRESCO_SEG)

    def detener(self):
        self.parar.set()
        soltar(self.carpeta)
