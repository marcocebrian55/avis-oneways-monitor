# -*- coding: utf-8 -*-
"""
Panel web del Monitor de Oneways.

Sirve para lo que hasta ahora obligaba a sentarse delante del portatil: ver que
esta pasando y cambiar la configuracion. Se llega desde el movil.

SOBRE LA SEGURIDAD, que es lo que decide todo el diseño de este fichero:
escucha SOLO en la direccion de Tailscale, que no existe en la internet
publica. Quien llega aqui ya ha demostrado ante Tailscale que pertenece a la
red privada, asi que el panel NO pide contraseña: inventarse un login propio
seria añadir una cerradura peor que la que ya hay. El precio es que la IP de
escucha no es negociable -- si alguien la cambia a 0.0.0.0 y abre el puerto,
este panel queda expuesto y con el las credenciales de Rentway.
"""
import os, sys, json, html, threading, datetime, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import avis_monitor as am
import credenciales

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse

app = FastAPI(title="AVIS · Monitor de Oneways")

ROJO = "#D4002B"
ROJO_OSC = "#A80022"
GRIS = "#F4F4F4"
_pasada = {"corriendo": False, "ultimo": None}


def _logo():
    """El banner de AVIS incrustado en la pagina.

    Va en base64 dentro del HTML y no como fichero aparte: son 15 KB y asi el
    panel es UNA sola respuesta, sin rutas estaticas que servir ni que se
    rompan si alguien mueve la carpeta assets/. Es el mismo PNG que usa la
    ventana de Windows, para que se vea igual."""
    import base64
    try:
        with open(am.resource(os.path.join("assets", "avis_banner.png")), "rb") as f:
            return ('<img src="data:image/png;base64,%s" alt="AVIS" '
                    'style="height:34px;vertical-align:middle">'
                    % base64.b64encode(f.read()).decode("ascii"))
    except Exception:
        return '<b style="color:%s;font-size:22px">AVIS</b>' % ROJO


# ----------------------------------------------------------------- plantilla
def _pagina(titulo, cuerpo, activa=""):
    def tab(ruta, texto):
        on = "border-bottom:3px solid %s;color:%s;font-weight:600" % (ROJO, ROJO)
        return ('<a href="%s" style="padding:10px 16px;text-decoration:none;'
                'color:#444;display:inline-block;%s">%s</a>'
                % (ruta, on if activa == ruta else "", texto))
    return HTMLResponse("""<!doctype html><html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s · AVIS Oneways</title><style>
 *{box-sizing:border-box} body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;
   background:#F4F4F6;color:#1b1b1f}
 header{background:#fff;border-bottom:4px solid %s;padding:14px 18px}
 header b{color:%s;font-size:19px} header span{color:#777;font-size:13px;margin-left:8px}
 nav{background:#fff;border-bottom:1px solid #e3e3e8;padding:0 8px;overflow-x:auto;white-space:nowrap}
 main{padding:16px;max-width:960px;margin:0 auto}
 .caja{background:#fff;border:1px solid #e3e3e8;border-radius:10px;padding:16px;margin-bottom:14px}
 .caja h2{margin:0 0 12px;font-size:14px;text-transform:uppercase;letter-spacing:.5px;color:#666}
 table{width:100%%;border-collapse:collapse;font-size:14px} th,td{text-align:left;padding:8px 6px;
   border-bottom:1px solid #eee} th{color:#777;font-weight:600;font-size:12px;text-transform:uppercase}
 .kv{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #f0f0f3;font-size:14px}
 .kv:last-child{border:0} .kv span:first-child{color:#666}
 .ok{color:#0a7d00;font-weight:600} .mal{color:#b00000;font-weight:600}
 button,.btn{background:%s;color:#fff;border:0;border-radius:7px;padding:11px 18px;font-size:15px;
   cursor:pointer;text-decoration:none;display:inline-block}
 button:disabled{background:#bbb} textarea,input{width:100%%;padding:10px;border:1px solid #ccc;
   border-radius:7px;font-size:15px;font-family:inherit} label{display:block;margin:10px 0 4px;
   font-size:13px;color:#555;font-weight:600}
 pre{background:#1b1b1f;color:#e6e6e6;padding:12px;border-radius:8px;overflow-x:auto;
   font-size:12px;line-height:1.5;max-height:65vh}
 .aviso{background:#FFF6E5;border:1px solid #F0D9A8;border-radius:8px;padding:10px 12px;
   font-size:13px;color:#6b5220;margin-bottom:12px}
</style></head><body>
<header>%s<span>Monitor de Oneways</span></header>
<nav>%s%s%s</nav><main>%s</main></body></html>"""
        % (html.escape(titulo), ROJO, ROJO, ROJO,
           _logo(),
           tab("/", "Estado"), tab("/registro", "Registro"), tab("/ajustes", "Ajustes"),
           cuerpo))


def _hace(dt):
    if not dt:
        return "nunca"
    m = (datetime.datetime.now() - dt).total_seconds() / 60.0
    if m < 60:
        return "hace %d min" % m
    if m < 48 * 60:
        return "hace %.1f h" % (m / 60.0)
    return "hace %d dias" % (m / 1440.0)


# -------------------------------------------------------------------- estado
@app.get("/", response_class=HTMLResponse)
def inicio():
    ultima = am._ultima_pasada()
    activos = am._oneways_activos()
    # Una pasada tarda ~75 s y corren cada 2 h: si la ultima es de hace mas de
    # 3 h, algo va mal y hay que verlo sin tener que interpretar una fecha.
    sano = ultima is not None and (datetime.datetime.now() - ultima).total_seconds() < 3 * 3600

    # Las MISMAS diez columnas que la tabla de la ventana de Windows, en el
    # mismo orden: quien usaba el .exe no tiene que reaprender nada.
    def _e(v):
        return html.escape(str(v or ""))

    filas = ""
    for i, r in enumerate(activos):
        filas += ('<tr%s><td>%s</td><td><b>%s</b></td><td>%s</td>'
                  '<td>%s → %s</td><td>%s</td><td>%s</td><td>%s</td>'
                  '<td>%s</td><td>%s</td><td>%s</td></tr>'
                  % (' style="background:#FAFAFB"' if i % 2 else "",
                     _e(r.get("tipo")), _e(r.get("num")),
                     _e(r.get("matricula") or "—"),
                     _e(r.get("salida")), _e(r.get("devolucion")),
                     _e(r.get("fecha_salida")), _e(r.get("fecha_llegada")),
                     _e(r.get("estado")), _e(r.get("cliente")),
                     _e(r.get("vuelo")),
                     _e(r.get("telefono") or r.get("telefono_conductor"))))
    if not filas:
        filas = ('<tr><td colspan="10" style="color:#888;padding:14px">'
                 'Ningún oneway activo ahora mismo.</td></tr>')

    # Panel de cambios de la última pasada, como el de la ventana.
    ult = _pasada.get("ultimo") or {}
    cambios = ult.get("cambios") or []
    if cambios:
        trozos = []
        for c in cambios:
            r = c.get("reg", {})
            if c.get("tipo") == "NUEVO":
                col, tit = "#0a7d00", "NUEVO ONEWAY"
                extra = "salida %s" % _e(r.get("fecha_salida"))
            elif c.get("tipo") == "DESAPARECIDO":
                col = "#b00000"
                tit = "ONEWAY ANULADO" if c.get("motivo") == "ANULADO" else "YA NO ES ONEWAY"
                extra = ""
            else:
                col, tit = "#b06a00", "CAMBIO"
                extra = "<br>".join("%s: %s → %s" % (_e(a), _e(b), _e(d))
                                    for a, b, d in c.get("difs", []))
            trozos.append(
                '<div style="border-left:4px solid %s;background:#FAFAFB;padding:9px 12px;'
                'margin-bottom:6px"><div style="color:%s;font-weight:600;font-size:12px">%s</div>'
                '<div><b>%s %s</b> · %s · %s → %s</div>'
                '<div style="color:#555;font-size:12px">%s</div></div>'
                % (col, col, tit, _e(r.get("tipo")), _e(r.get("num")),
                   _e(r.get("matricula") or "sin matrícula"),
                   _e(r.get("salida")), _e(r.get("devolucion")), extra))
        panel_cambios = ('<div class="caja"><h2>Cambios de la última revisión</h2>%s</div>'
                         % "".join(trozos))
    elif ult:
        panel_cambios = ('<div class="caja"><h2>Cambios de la última revisión</h2>'
                         '<p style="color:#888;margin:0">Sin cambios.</p></div>')
    else:
        panel_cambios = ""

    corriendo = _pasada["corriendo"]
    cuerpo = """
<div class="caja"><h2>Estado</h2>
  <div class="kv"><span>Vigilancia</span><span class="%s">%s</span></div>
  <div class="kv"><span>Última pasada</span><span>%s%s</span></div>
  <div class="kv"><span>Próxima</span><span>%s</span></div>
  <div class="kv"><span>Oneways activos</span><span>%d</span></div>
</div>
<div class="caja"><h2>Oneways activos <span style="color:#8A8A90;font-weight:400">· %d</span></h2>
  <div style="overflow-x:auto">
  <table><tr><th>Tipo</th><th>Nº</th><th>Matrícula</th><th>Ruta</th><th>Salida</th>
    <th>Llegada</th><th>Estado</th><th>Cliente</th><th>Vuelo</th><th>Teléfono</th></tr>
  %s</table></div>
</div>
%s
<div class="caja"><h2>Forzar una revisión</h2>
  <p style="color:#666;font-size:14px;margin-top:0">Descarga los informes de Rentway y avisa
     si hay cambios. Tarda algo más de un minuto.</p>
  <form method="post" action="/revisar">
    <button %s>%s</button>
  </form>
</div>""" % ("ok" if sano else "mal",
             "funcionando" if sano else "REVISAR: sin pasadas recientes",
             ultima.strftime("%d/%m/%Y %H:%M") if ultima else "nunca",
             "  ·  " + _hace(ultima) if ultima else "",
             am._proxima_pasada().strftime("%d/%m/%Y %H:%M"),
             len(activos), len(activos), filas, panel_cambios,
             "disabled" if corriendo else "",
             "Revisando…" if corriendo else "Revisar ahora")
    return _pagina("Estado", cuerpo, "/")


@app.post("/revisar")
def revisar():
    """Lanza la pasada en un hilo y vuelve al momento.

    No se espera al resultado a proposito: la pasada tarda mas de un minuto y
    el movil habria cortado la conexion. El candado de instancia.BloqueoLocal
    ya impide que se solapen dos, asi que pulsar dos veces no rompe nada.
    """
    if not _pasada["corriendo"]:
        def faena():
            _pasada["corriendo"] = True
            try:
                _pasada["ultimo"] = am.ejecutar_pasada(quien="panel")
            except Exception as e:
                _pasada["ultimo"] = {"estado": "error", "error": str(e)[:200]}
            finally:
                _pasada["corriendo"] = False
        threading.Thread(target=faena, daemon=True).start()
    return RedirectResponse("/", status_code=303)


# ------------------------------------------------------------------ registro
@app.get("/registro", response_class=HTMLResponse)
def registro():
    p = os.path.join(am.app_dir(), "avis_oneways.log")
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            lineas = f.readlines()[-300:]
        texto = html.escape("".join(lineas))
    except Exception as e:
        texto = html.escape("No pude leer el registro: %s" % e)
    return _pagina("Registro",
                   '<div class="caja"><h2>Últimas 300 líneas</h2><pre>%s</pre></div>' % texto,
                   "/registro")


# ------------------------------------------------------------------- ajustes
@app.get("/ajustes", response_class=HTMLResponse)
def ajustes(hecho: str = ""):
    base = am.app_dir()
    cfg = credenciales.cargar_correo(base) or {}
    usuario, _ = credenciales.cargar(base)
    _, chat = credenciales.cargar_telegram(base)
    dest = str(cfg.get("destinatarios", ""))
    lista = [d.strip() for d in dest.replace(";", ",").split(",") if d.strip()]

    nota = ('<div class="aviso">%s</div>' % html.escape(hecho)) if hecho else ""
    cuerpo = """%s
<div class="caja"><h2>Destinatarios del correo (%d)</h2>
  <form method="post" action="/ajustes/destinatarios">
    <p style="color:#666;font-size:13px;margin-top:0">Uno por línea. Reciben las altas,
       las bajas y los cambios, lo mismo que el grupo de Telegram.</p>
    <textarea name="destinatarios" rows="12">%s</textarea>
    <p><button>Guardar</button></p>
  </form>
</div>
<div class="caja"><h2>Probar el correo</h2>
  <form method="post" action="/ajustes/probar">
    <p style="color:#666;font-size:13px;margin-top:0">Manda un correo de prueba. Déjalo
       vacío para mandarlo a los %d destinatarios.</p>
    <input name="destino" placeholder="una direccion@ejemplo.com (opcional)">
    <p><button>Enviar prueba</button></p>
  </form>
</div>
<div class="caja"><h2>Conexiones</h2>
  <div class="kv"><span>Usuario de Rentway</span><span>%s</span></div>
  <div class="kv"><span>Chat de Telegram</span><span>%s</span></div>
  <div class="kv"><span>Servidor de correo</span><span>%s:%s</span></div>
  <div class="kv"><span>Se envía desde</span><span>%s</span></div>
  <p style="color:#888;font-size:12px;margin-bottom:0">Las contraseñas no se muestran nunca.
     Para cambiarlas, edita <code>configuracion.json</code> en el servidor.</p>
</div>""" % (nota, len(lista), html.escape("\n".join(lista)), len(lista),
             html.escape(usuario or "(sin configurar)"),
             html.escape(str(chat or "(sin configurar)")),
             html.escape(str(cfg.get("servidor", "-"))), html.escape(str(cfg.get("puerto", "-"))),
             html.escape(str(cfg.get("remitente") or cfg.get("usuario") or "-")))
    return _pagina("Ajustes", cuerpo, "/ajustes")


@app.post("/ajustes/destinatarios")
def guardar_destinatarios(destinatarios: str = Form("")):
    base = am.app_dir()
    cfg = credenciales.cargar_correo(base) or {}
    limpio, malas = [], []
    for linea in destinatarios.replace(",", "\n").replace(";", "\n").splitlines():
        d = linea.strip()
        if not d:
            continue
        # Validacion a proposito tosca pero util: una direccion mal escrita no
        # da error al guardar, da un rebote silencioso dias despues.
        if d.count("@") == 1 and "." in d.split("@")[1] and " " not in d:
            if d.lower() not in [x.lower() for x in limpio]:
                limpio.append(d)
        else:
            malas.append(d)
    credenciales.guardar_correo(base, cfg.get("servidor", "smtp.gmail.com"),
                                cfg.get("puerto", "587"), cfg.get("usuario", ""),
                                cfg.get("clave", ""), " , ".join(limpio),
                                cfg.get("remitente", ""))
    msg = "Guardados %d destinatarios." % len(limpio)
    if malas:
        msg += "  DESCARTADAS por no parecer direcciones: " + ", ".join(malas)
    return RedirectResponse("/ajustes?hecho=" + msg.replace("&", ""), status_code=303)


@app.post("/ajustes/probar")
def probar(destino: str = Form("")):
    ok = am.probar_correo(destino.strip() or None)
    return RedirectResponse(
        "/ajustes?hecho=" + ("Correo de prueba enviado." if ok else
                             "NO se pudo enviar. Mira el registro."),
        status_code=303)


@app.get("/salud", response_class=PlainTextResponse)
def salud():
    u = am._ultima_pasada()
    return "ok %s" % (u.isoformat() if u else "sin-pasadas")
