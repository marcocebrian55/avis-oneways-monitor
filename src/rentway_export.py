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
        u.wait_for(state="visible", timeout=20000)
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


def _un_informe(pg, url, f_ini, f_fin, destino, etiqueta, log, esperar_login,
               credenciales=None):
    log("  [%s] abriendo informe..." % etiqueta)
    _abrir_informe(pg, url, etiqueta, log, esperar_login, credenciales)

    _rellenar_fecha(pg, 0, f_ini, log)
    _rellenar_fecha(pg, 1, f_fin, log)

    btn = pg.get_by_role("button", name="Generar informe")
    if btn.get_attribute("aria-disabled") == "true":
        raise RuntimeError("[%s] 'Generar informe' sigue deshabilitado: revisa los parámetros." % etiqueta)
    btn.click()
    log("  [%s] generando informe..." % etiqueta)
    pg.wait_for_url("**/result", timeout=180000)
    pg.wait_for_timeout(4000)

    with pg.expect_download(timeout=180000) as di:
        pg.get_by_role("button", name="Excel").click()
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
        ctx = p.chromium.launch_persistent_context(
            perfil, headless=not visible, accept_downloads=True,
            args=["--no-first-run", "--no-default-browser-check",
                  "--disable-background-timer-throttling"],
            viewport=None if visible else {"width": 1600, "height": 1000},
            **extra
        )
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
                                                     credenciales)
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
                                                     etiqueta, log, esperar_login, credenciales)
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
