# -*- coding: utf-8 -*-
"""
Extracción automática de los 2 Excels de ONEWAYS desde Rentway (Playwright).

Informes usados (Rentway v5.26, aviscanarias.jimpisoft.pt):
  - Informes > Reservas  > "Lista de reservas"  -> /reports/reservations/2126
        parámetros: Fecha desde* / Fecha hasta*   -> reservations_list_*.xlsx
  - Informes > Contratos > "Abiertos"           -> /reports/rental agreements/2094
        parámetros: Intervalo fechas* (inicial/final) -> open_*.xlsx

En ambos: rellenar los 2 dateboxes -> "Generar informe" -> la vista /result
trae los botones "PDF" y "Excel"; el de Excel dispara la descarga.

El navegador usa un PERFIL PERSISTENTE, así que la sesión de Rentway se
mantiene entre ejecuciones. La primera vez (o cuando caduque) hay que
iniciar sesión a mano: `descargar_informes(..., esperar_login=N)` deja
la ventana abierta esperando hasta N segundos.
"""
import os
import glob
import datetime

RENTWAY = "https://aviscanarias.jimpisoft.pt"
INFORME_RESERVAS = RENTWAY + "/reports/reservations/2126"
INFORME_ABIERTOS = RENTWAY + "/reports/rental%20agreements/2094"

# Informes BASE: definen qué es oneway (llevan estación de salida Y de devolución).
INFORMES_BASE = [
    ("reservas", "Reservas",  INFORME_RESERVAS),   # -> reservations_list_*.xlsx
    ("abiertos", "Abiertos",  INFORME_ABIERTOS),   # -> open_*.xlsx
]

# Informes AMPLIADOS: no detectan oneways, los enriquecen.
#  2119 -> vuelo, lugar de entrega, observaciones, extras, CDW/TP/PAI, franquicia
#  2092 -> contratos anulados (distinguir "anulado" de "terminado")
#  2162 / 2163 -> correo y teléfono de cliente y conductor
INFORMES_EXTRA = [
    ("detalle",      "Detalle reservas",   RENTWAY + "/reports/reservations/2119"),
    ("anulados",     "Anulados",           RENTWAY + "/reports/rental%20agreements/2092"),
    ("contacto_res", "Contacto reservas",  RENTWAY + "/reports/reservations/2162"),
    ("contacto_con", "Contacto contratos", RENTWAY + "/reports/rental%20agreements/2163"),
]

# Los ampliados se piden con ventana hacia atrás: un contrato anulado o una
# reserva ya creada pueden tener fecha de salida anterior a hoy.
DIAS_ATRAS_EXTRA = 60

PERFIL_DEFECTO = os.path.join(os.path.expanduser("~"), "chrome-rentway-profile2")

# Rentway sirve la interfaz EN EL IDIOMA QUE PIDE EL NAVEGADOR, y este fichero
# busca los elementos por su texto en español ("Nombre de usuario",
# "Contraseña", "Inicio de sesión", "Generar informe"). En Windows funcionaba
# de casualidad: Chromium heredaba el español del sistema. En el servidor
# (Ubuntu en Alemania) arranca en en-US, Rentway devolvia la pagina en INGLES
# con aria-label='Username', y NINGUN selector encontraba nada. El sintoma no
# decia una palabra del idioma: "Timeout 20000ms" y "no hay credenciales
# validas guardadas", o sea que parecia un problema de contraseña.
# Medido el 24/08/2026 en el servidor: document.documentElement.lang == "en"
# y navigator.languages == ["en-US","en"].
IDIOMA = "es-ES"

# La zona horaria del navegador tambien se fija a proposito: los campos de
# fecha se rellenan como DD/MM/YYYY calculados con la hora local del proceso.
# Si el navegador estuviera en otro huso, un informe pedido a ultima hora del
# dia podria irse al dia siguiente.
ZONA_HORARIA = "Atlantic/Canary"


def _preparar_navegadores(base):
    """Localiza el Chromium de Playwright.

    Dentro de un .exe de PyInstaller, Playwright busca los navegadores en la
    copia temporal del driver (_MEIxxxx\\...\\.local-browsers), que está vacía,
    y falla con "Executable doesn't exist". Hay que apuntarle a mano:
      1) carpeta 'ms-playwright' junto al .exe (modo portable, otro PC), o
      2) la instalación normal del usuario en %LOCALAPPDATA%\\ms-playwright.
    """
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return os.environ["PLAYWRIGHT_BROWSERS_PATH"]
    candidatos = [
        os.path.join(base, "ms-playwright"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright"),
        # Linux: donde los deja `playwright install chromium` en un servidor.
        os.path.join(os.path.expanduser("~"), ".cache", "ms-playwright"),
        "/ms-playwright",                     # imagen oficial de Playwright
    ]
    for c in candidatos:
        if c and os.path.isdir(c) and glob.glob(os.path.join(c, "chromium-*")):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = c
            return c
    raise RuntimeError(
        "No encuentro los navegadores de Playwright (Chromium).\n\n"
        "Copia la carpeta 'ms-playwright' junto a este programa, o instálalos "
        "con 'playwright install chromium'.\n\nHe buscado en:\n  - "
        + "\n  - ".join(c for c in candidatos if c))


def _boton(pg, *nombres):
    """Primer boton que exista con alguno de esos nombres.

    El contexto se abre con locale es-ES, asi que lo normal es acertar con el
    primero. La lista existe por un caso concreto y caro: un perfil creado
    ANTES de fijar el idioma guarda el idioma elegido entonces, y la SPA de
    Rentway sigue usandolo aunque el navegador pida español. Paso el
    24/08/2026 en el servidor y el sintoma fue un 'Timeout 30000ms' sobre
    get_attribute, que no sugiere el idioma ni de lejos.

    (Si vuelve a pasar, la solucion de raiz es borrar la carpeta del perfil.)
    """
    ultimo = None
    for n in nombres:
        loc = pg.get_by_role("button", name=n)
        try:
            if loc.count():
                return loc
        except Exception:
            pass
        ultimo = loc
    return ultimo


def _perfil_ocupado(perfil):
    """True si la carpeta de perfil parece estar tomada por otro Chromium.

    No hay forma limpia y multiplataforma de preguntarlo, asi que se mira el
    candado que deja el propio navegador: 'SingletonLock' en Linux (un enlace
    simbolico) y 'lockfile' en Windows. Solo sirve para dar un mensaje mejor
    cuando el arranque YA ha fallado, asi que un falso positivo no rompe nada.
    """
    try:
        for nombre in ("SingletonLock", "lockfile"):
            if os.path.lexists(os.path.join(perfil, nombre)):
                return True
    except Exception:
        pass
    return False


CAJA_FECHA = ".dx-datebox input.dx-texteditor-input"


def _esperar_parametros(pg, etiqueta, log, timeout=45000):
    """Espera a que Rentway PINTE los campos de fecha.

    POR QUE: antes se hacía `wait_for_timeout(3500)` y se buscaba el campo a
    continuación. Rentway monta esos widgets con JavaScript (DevExtreme), así
    que si un día va lento —servidor cargado, red con hipo— a los 3,5 s todavía
    no existen y la pasada moría con "No encuentro el campo de fecha".
    Paso real: 07/08/2026 16:00, cuatro intentos seguidos fallidos justo después
    de un corte de red. Esperar al elemento en vez de contar segundos aguanta
    lo que haga falta y sigue en cuanto está listo.
    """
    try:
        pg.wait_for_selector(CAJA_FECHA, state="visible", timeout=timeout)
        return
    except Exception:
        pass
    # No aparecieron: dejamos constancia de DONDE estabamos, que es lo que
    # faltaba para diagnosticar sin tener que reproducirlo a mano.
    try:
        titulo, url = pg.title(), pg.url
    except Exception:
        titulo, url = "?", "?"
    pista = ""
    if "/login" in url.lower() or "sesi" in titulo.lower():
        pista = " Parece la pantalla de acceso: la sesión ha caducado."
    raise RuntimeError(
        "[%s] Rentway no mostró los campos de fecha en %d s.%s (url=%s, título=%r)"
        % (etiqueta, timeout // 1000, pista, url[:120], titulo[:60]))


def _rellenar_fecha(pg, idx, texto, log):
    cajas = pg.locator(CAJA_FECHA)
    if cajas.count() <= idx:
        raise RuntimeError("No encuentro el campo de fecha nº %d en el informe." % (idx + 1))
    inp = cajas.nth(idx)
    inp.click()
    pg.wait_for_timeout(250)
    inp.press("Control+a")
    pg.keyboard.type(texto, delay=35)
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(700)
    log("    fecha %d: %s" % (idx + 1, inp.input_value()))


def entrar_con_credenciales(pg, usuario, clave, log=print):
    """Rellena el formulario de login de Rentway y entra.

    Campos (Rentway v5.26): input[aria-label='Nombre de usuario'] y
    input[aria-label='Contraseña']; boton 'Inicio de sesión'.
    Imprescindible para el modo desatendido: la cookie del perfil CADUCA
    (comprobado: a los 3 dias volvia a pedir login).
    """
    try:
        u = pg.locator("input[aria-label='Nombre de usuario']").first
        try:
            u.wait_for(state="visible", timeout=20000)
        except Exception:
            # Segunda oportunidad SIN depender del idioma. No deberia hacer
            # falta porque el contexto se abre con locale es-ES, pero si algun
            # dia Rentway decide el idioma por otra via (perfil del usuario,
            # cabecera del servidor), el fallo era invisible: se veia un
            # timeout y un mensaje sobre credenciales invalidas, y se perdian
            # horas mirando la contraseña. Aqui se busca por estructura: la
            # caja de contraseña es la unica type=password de la pagina, y el
            # usuario es la caja de texto que la precede.
            log("  El formulario no esta en español; busco los campos por estructura.")
            c0 = pg.locator("input[type='password']").first
            c0.wait_for(state="visible", timeout=20000)
            u = pg.locator("input:not([type='password'])").first
            u.wait_for(state="visible", timeout=10000)
            c = c0
            u.click(); u.fill(""); u.type(usuario, delay=25)
            c.click(); c.fill(""); c.type(clave, delay=25)
            c.press("Enter")
            for _ in range(20):
                pg.wait_for_timeout(1000)
                if "/login" not in pg.url:
                    log("  Sesión iniciada automáticamente como %s." % usuario)
                    pg.wait_for_timeout(2000)
                    return True
            log("  El login automático no paso de la pantalla de acceso.")
            return False
        c = pg.locator("input[aria-label='Contraseña']").first
        u.click(); u.fill(""); u.type(usuario, delay=25)
        c.click(); c.fill(""); c.type(clave, delay=25)
        pg.wait_for_timeout(300)
        b = pg.get_by_role("button", name="Inicio de sesión")
        pulsado = False
        for k in range(b.count()):
            if b.nth(k).is_visible():
                b.nth(k).click(timeout=10000)
                pulsado = True
                break
        if not pulsado:
            c.press("Enter")
        for _ in range(20):
            pg.wait_for_timeout(1000)
            if "/login" not in pg.url:
                log("  Sesión iniciada automáticamente como %s." % usuario)
                pg.wait_for_timeout(2000)
                return True
        log("  El login automático no paso de la pantalla de acceso.")
        return False
    except Exception as e:
        log("  Error en el login automático: %s" % str(e).split("\n")[0][:90])
        return False


def _esperar_sesion(pg, segundos, log, credenciales=None):
    """Si Rentway pide login: primero intenta entrar solo con las credenciales
    guardadas; si no hay o fallan, espera a que se entre a mano."""
    import time
    if "/login" not in pg.url:
        return True
    if credenciales and credenciales[0] and credenciales[1]:
        log("  Rentway pide login: entrando con las credenciales guardadas...")
        if entrar_con_credenciales(pg, credenciales[0], credenciales[1], log):
            return True
    if segundos <= 0:
        raise RuntimeError("Rentway pide iniciar sesión y no hay credenciales validas guardadas.")
    log("  Rentway pide login. Inicia sesión en la ventana del navegador...")
    t0 = time.time()
    while time.time() - t0 < segundos:
        if "/login" not in pg.url:
            log("  Sesión iniciada.")
            pg.wait_for_timeout(2000)
            return True
        time.sleep(2)
    raise RuntimeError("Se agotó la espera de inicio de sesión en Rentway.")


def _abrir_informe(pg, url, etiqueta, log, esperar_login, credenciales):
    """Deja la pagina del informe lista, recuperandose de la sesion zombi.

    LA TRAMPA (07/08/2026): la sesion de Rentway puede quedarse a medias —sigue
    valiendo para /dashboard pero NO para /reports—, y en vez de mandarte al
    login te sirve su propia pagina /error con un 404. Como la URL nunca
    contiene "/login", la comprobacion de sesion no se enteraba y la pasada
    moria sin saber por que.

    Comprobado: RECARGAR NO SIRVE (8 intentos seguidos, /error las 8 veces).
    Lo unico que lo arregla es VOLVER A INICIAR SESION; despues funciona al
    primer intento.
    """
    pg.goto(url, wait_until="domcontentloaded", timeout=90000)
    pg.wait_for_timeout(3000)
    _esperar_sesion(pg, esperar_login, log, credenciales)

    if "/error" in pg.url or pg.locator(CAJA_FECHA).count() < 2:
        log("  [%s] la sesión no sirve para informes: vuelvo a entrar…" % etiqueta)
        if not (credenciales and credenciales[0] and credenciales[1]):
            raise RuntimeError(
                "[%s] Rentway devuelve /error y no hay credenciales guardadas para "
                "volver a entrar. Abre el programa y guarda usuario y contraseña."
                % etiqueta)
        pg.goto(RENTWAY + "/login", wait_until="domcontentloaded", timeout=90000)
        pg.wait_for_timeout(2000)
        if not entrar_con_credenciales(pg, credenciales[0], credenciales[1], log):
            raise RuntimeError("[%s] No pude volver a iniciar sesión en Rentway." % etiqueta)
        pg.goto(url, wait_until="domcontentloaded", timeout=90000)
        pg.wait_for_timeout(3000)

    _esperar_parametros(pg, etiqueta, log)


def _diagnostico(pg, etiqueta, base_app, log):
    """Deja constancia de QUE habia en pantalla cuando un informe reviento.

    POR QUE: el informe de Abiertos lleva desde el 25/08/2026 colgandose cinco
    veces por noche y lo unico que sabemos es "Timeout 180000ms exceeded". Eso
    no distingue entre Rentway en mantenimiento, un error que la pagina esta
    mostrando, una sesion caducada o un informe que de verdad tarda. Tres noches
    de datos y ninguna pista, porque nadie miro la pantalla: no habia nadie.

    Nunca lanza. Un fallo recogiendo pistas no puede tapar el fallo de verdad.
    """
    datos = []
    try:
        datos.append("url=" + str(pg.url)[:200])
    except Exception:
        pass
    try:
        datos.append("titulo=" + str(pg.title())[:120])
    except Exception:
        pass
    try:
        texto = pg.locator("body").inner_text(timeout=5000)
        datos.append("pantalla=" + " ".join(texto.split())[:400])
    except Exception:
        datos.append("pantalla=(no se pudo leer)")
    if datos:
        log("  [%s] que habia en pantalla: %s" % (etiqueta, " | ".join(datos)))
    try:
        carpeta = os.path.join(base_app or os.getcwd(), "diagnostico")
        os.makedirs(carpeta, exist_ok=True)
        sello = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        ruta = os.path.join(carpeta, "%s_%s.png" % (etiqueta.replace(" ", "_"), sello))
        pg.screenshot(path=ruta, full_page=False, timeout=10000)
        log("  [%s] captura: %s" % (etiqueta, ruta))
        # Sin poda esto llena el disco: 12 pasadas al dia por 2 intentos.
        viejas = sorted(glob.glob(os.path.join(carpeta, "*.png")))
        for f in viejas[:-40]:
            try:
                os.remove(f)
            except Exception:
                pass
    except Exception as e:
        log("  [%s] no pude sacar la captura: %s" % (etiqueta, str(e)[:100]))


def _un_informe(pg, url, f_ini, f_fin, destino, etiqueta, log, esperar_login,
               credenciales=None, base_app=None):
    log("  [%s] abriendo informe..." % etiqueta)
    _abrir_informe(pg, url, etiqueta, log, esperar_login, credenciales)

    _rellenar_fecha(pg, 0, f_ini, log)
    _rellenar_fecha(pg, 1, f_fin, log)

    btn = _boton(pg, "Generar informe", "Generate report")
    if btn.get_attribute("aria-disabled") == "true":
        raise RuntimeError("[%s] 'Generar informe' sigue deshabilitado: revisa los parámetros." % etiqueta)
    btn.click()
    log("  [%s] generando informe..." % etiqueta)
    try:
        pg.wait_for_url("**/result", timeout=180000)
        pg.wait_for_timeout(4000)

        with pg.expect_download(timeout=180000) as di:
            pg.get_by_role("button", name="Excel").click()
    except Exception:
        # Aqui es donde muere el informe de Abiertos de madrugada. Se miran las
        # pistas ANTES de propagar, que es el unico momento en que la pagina
        # sigue en pie y se puede preguntar que esta mostrando.
        _diagnostico(pg, etiqueta, base_app, log)
        raise
    d = di.value
    ruta = os.path.join(destino, d.suggested_filename)
    d.save_as(ruta)
    log("  [%s] descargado: %s" % (etiqueta, os.path.basename(ruta)))
    return ruta


def descargar_informes(destino, dias=7, perfil=None, visible=False,
                       esperar_login=300, log=print, base_app=None, ampliado=True,
                       credenciales=None, progreso=None):
    """Descarga los Excels en 'destino'.

    Devuelve {clave: ruta}. Siempre los 2 informes BASE; con ampliado=True
    añade los 4 de enriquecimiento. Un fallo en un informe ampliado NO aborta
    la descarga: se anota y se sigue (el motor funciona igual sin ellos).
    """
    from playwright.sync_api import sync_playwright

    os.makedirs(destino, exist_ok=True)
    ruta_nav = _preparar_navegadores(base_app or os.path.dirname(os.path.abspath(__file__)))
    log("Navegadores Playwright: %s" % ruta_nav)
    perfil = perfil or PERFIL_DEFECTO

    hoy = datetime.date.today()
    fin = hoy + datetime.timedelta(days=dias)
    f_ini = hoy.strftime("%d/%m/%Y") + ", 00:00"
    f_fin = fin.strftime("%d/%m/%Y") + ", 23:59"
    # ventana ampliada hacia atrás para los informes de enriquecimiento
    x_ini = (hoy - datetime.timedelta(days=DIAS_ATRAS_EXTRA)).strftime("%d/%m/%Y") + ", 00:00"
    log("Rango solicitado: %s  ->  %s" % (f_ini, f_fin))
    if ampliado:
        log("Rango de los datos ampliados: %s  ->  %s" % (x_ini, f_fin))

    salidas = {}
    with sync_playwright() as p:
        # En modo invisible hay que pedir channel="chromium" para que use el
        # navegador NORMAL. Sin eso Playwright busca 'chrome-headless-shell',
        # un binario aparte de 267 MB que no vale la pena empaquetar.
        extra = {} if visible else {"channel": "chromium"}
        args = ["--no-first-run", "--no-default-browser-check",
                "--disable-background-timer-throttling",
                "--lang=" + IDIOMA]
        if os.name != "nt":
            # En un contenedor /dev/shm son 64 MB por defecto y Chromium se cae
            # a pedazos. Con esto usa /tmp. No estorba en un VPS normal.
            args.append("--disable-dev-shm-usage")
        try:
            ctx = p.chromium.launch_persistent_context(
                perfil, headless=not visible, accept_downloads=True,
                args=args,
                # IMPRESCINDIBLE, no es cosmetico: ver la nota de IDIOMA.
                locale=IDIOMA, timezone_id=ZONA_HORARIA,
                viewport=None if visible else {"width": 1600, "height": 1000},
                **extra
            )
        except Exception as e:
            # Si OTRO Chromium tiene abierto este perfil, Playwright muere con
            # un TargetClosedError de cuarenta lineas que no menciona la
            # palabra "perfil" por ningun lado. Paso de verdad el 24/08/2026:
            # un navegador olvidado cuatro dias antes con
            # --remote-debugging-port bloqueaba la carpeta y el log no daba la
            # menor pista. En un servidor desatendido eso es una hora de
            # diagnostico a ciegas.
            if _perfil_ocupado(perfil):
                raise RuntimeError(
                    "El perfil del navegador esta EN USO por otro Chromium." +
                    os.linesep + "  Perfil: " + str(perfil) + os.linesep +
                    "Cierra ese navegador, o pasa otra carpeta de perfil, y "
                    "vuelve a intentarlo.") from e
            raise
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            lista = list(INFORMES_BASE) + (list(INFORMES_EXTRA) if ampliado else [])
            total = len(lista)
            hecho = 0

            def paso(etiqueta):
                if progreso:
                    try:
                        progreso(hecho, total, etiqueta)
                    except Exception:
                        pass

            for clave, etiqueta, url in INFORMES_BASE:
                paso("Descargando: %s" % etiqueta)
                # Los informes BASE se reintentan: un fallo puntual de red o un
                # informe que tarda de mas no debe tirar la pasada entera.
                salidas[clave] = None
                for intento in (1, 2):
                    try:
                        salidas[clave] = _un_informe(pg, url, f_ini, f_fin, destino,
                                                     etiqueta, log, esperar_login,
                                                     credenciales, base_app)
                        break
                    except Exception as e:
                        log("  [%s] intento %d fallido: %s"
                            % (etiqueta, intento, str(e).split("\n")[0][:110]))
                        if intento == 1:
                            log("  [%s] reintentando en 15 s…" % etiqueta)
                            pg.wait_for_timeout(15000)
                hecho += 1
                paso("Descargado: %s" % etiqueta)
            if not salidas.get("reservas"):
                # sin el informe de reservas no hay nada que analizar
                raise RuntimeError("No se pudo descargar el informe de reservas "
                                   "tras dos intentos.")
            if not salidas.get("abiertos"):
                log("  AVISO: sigo SIN el informe de Abiertos. Analizo solo con "
                    "reservas (los oneways de contratos no se veran esta vez).")
            if ampliado:
                for clave, etiqueta, url in INFORMES_EXTRA:
                    paso("Descargando: %s" % etiqueta)
                    try:
                        salidas[clave] = _un_informe(pg, url, x_ini, f_fin, destino,
                                                     etiqueta, log, esperar_login, credenciales,
                                                     base_app)
                    except Exception as e:
                        salidas[clave] = None
                        log("  [%s] AVISO: no se pudo descargar (%s). Se continúa sin él."
                            % (etiqueta, str(e).split("\n")[0][:120]))
                    hecho += 1
                    paso("Descargado: %s" % etiqueta)
            return salidas
        finally:
            ctx.close()


if __name__ == "__main__":
    import sys
    carpeta = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.expanduser("~"), "Downloads")
    dias = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    for k, v in descargar_informes(carpeta, dias=dias).items():
        print("  %-13s %s" % (k, os.path.basename(v) if v else "(no descargado)"))
