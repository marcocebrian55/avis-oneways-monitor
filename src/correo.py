# -*- coding: utf-8 -*-
"""
Avisos por correo (SMTP).

Solo biblioteca estandar (smtplib + email), asi que no engorda el .exe.
La contraseña de la cuenta emisora se guarda CIFRADA con DPAPI, igual que el
resto de secretos.

Sobre los servidores mas habituales:
  Gmail / Google Workspace : smtp.gmail.com       puerto 587 (STARTTLS)
        OJO: con verificacion en dos pasos hay que usar una "contraseña de
        aplicacion", la del usuario NO vale.
  Microsoft 365 / Outlook  : smtp.office365.com   puerto 587 (STARTTLS)
  Otros                    : preguntar al proveedor; 465 suele ser SSL directo.
"""
import smtplib, ssl
from email.message import EmailMessage
from email.utils import formataddr


def _conectar(servidor, puerto, usuario, clave, timeout=30):
    puerto = int(puerto)
    if puerto == 465:                     # SSL desde el principio
        ctx = ssl.create_default_context()
        s = smtplib.SMTP_SSL(servidor, puerto, timeout=timeout, context=ctx)
    else:                                 # 587 y demas: STARTTLS
        s = smtplib.SMTP(servidor, puerto, timeout=timeout)
        s.ehlo()
        try:
            s.starttls(context=ssl.create_default_context())
            s.ehlo()
        except Exception:
            pass                          # servidor interno sin TLS
    if usuario:
        s.login(usuario, clave)
    return s


def comprobar(servidor, puerto, usuario, clave):
    """Valida servidor y credenciales sin enviar nada."""
    s = _conectar(servidor, puerto, usuario, clave)
    s.quit()
    return True


def enviar(servidor, puerto, usuario, clave, destinatarios, asunto, cuerpo_html,
           remitente=None, log=None, oculto=False):
    """Envia el aviso. Devuelve True/False y NUNCA lanza: un fallo de correo no
    debe tumbar la vigilancia.

    `oculto=True` manda la lista en **Bcc** y deja en el To: el propio buzon
    emisor. Se usa en los avisos a las oficinas, que desde el 25/08/2026 son 28
    direcciones de las cuatro islas: en el To: se ven todas entre si y cualquiera
    puede contestar a todos sin querer, convirtiendo un aviso automatico en un
    hilo de 28 personas.

    Ojo con el To: al buzon emisor: NO es adorno. Un mensaje sin cabecera To:
    parece correo masivo y se lo comen los filtros de spam, que es justo lo peor
    que le puede pasar a un aviso que solo llega cuando hay algo que hacer.

    No hace falta borrar el Bcc a mano: `send_message` cuenta a esos
    destinatarios en el sobre pero nunca transmite la cabecera.
    """
    try:
        if isinstance(destinatarios, str):
            destinatarios = [d.strip() for d in destinatarios.replace(";", ",").split(",")
                             if d.strip()]
        if not destinatarios:
            return False
        m = EmailMessage()
        m["Subject"] = asunto
        m["From"] = formataddr(("AVIS · Monitor de Oneways", remitente or usuario))
        if oculto:
            visible = remitente or usuario
            m["To"] = formataddr(("AVIS · Monitor de Oneways", visible))
            # Fuera de la copia oculta el que ya va en el To:, o le llegaria el
            # mismo aviso DOS veces: el buzon emisor suele estar tambien en la
            # lista de destinatarios (aucc.rentway@ lo esta).
            copia = [d for d in destinatarios if d.lower() != (visible or "").lower()]
            if copia:
                m["Bcc"] = ", ".join(copia)
        else:
            m["To"] = ", ".join(destinatarios)
        m.set_content("Este aviso se ve mejor en un lector con formato HTML.")
        m.add_alternative(cuerpo_html, subtype="html")
        s = _conectar(servidor, puerto, usuario, clave)
        s.send_message(m)
        s.quit()
        return True
    except Exception as e:
        if log:
            log("  No pude enviar el correo: %s" % str(e)[:140])
        return False


# ---------------- composicion del mensaje ----------------
_ROJO = "#D4002B"


def _esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def cuerpo_fallo(mensaje, cuando=None, servidor=None):
    """Cuerpo del aviso de ERROR. Va solo a quien mantiene el sistema.

    POR QUE EXISTE: el fallo se avisaba unicamente por Telegram, y desde el
    servidor Telegram se cae a ratos (timeouts de lectura contra api.telegram.org
    varias veces al dia). Un aviso de averia que viaja por el mismo canal que
    se puede averiar no sirve de mucho; el correo es la segunda pata.

    Deliberadamente feo y directo: aqui no se viene a leer, se viene a enterarse
    de que hay que mirar el log."""
    return """<html><body style="font-family:Segoe UI,Arial,sans-serif;color:#222">
<div style="border-top:4px solid %s;padding-top:10px;max-width:640px">
  <div style="font-size:18px;font-weight:bold;color:%s">AVIS &middot; Monitor de Oneways</div>
  <div style="font-size:15px;font-weight:bold;margin:10px 0 4px">&#9888; La revisi&oacute;n autom&aacute;tica ha fallado</div>
  <div style="color:#444;font-size:14px">
     No se ha podido comprobar si hay oneways nuevos. Mientras siga as&iacute;,
     <b>no recibir&aacute;s avisos de cambios</b>: el silencio no significa que
     no haya novedades.</div>
  <div style="margin:14px 0;padding:10px 12px;background:#FAFAFB;border-left:4px solid %s">
     <div style="color:#666;font-size:12px;margin-bottom:4px">%s</div>
     <code style="font-size:13px;word-break:break-word">%s</code></div>
  <div style="color:#444;font-size:14px">
     Se reintentar&aacute; en la siguiente pasada. Si te llega esto varias veces
     seguidas, hay que mirarlo:
     <div style="margin-top:6px;font-family:Consolas,monospace;font-size:12.5px;color:#333">
       ssh root@%s<br>
       tail -60 /var/lib/oneways/avis_oneways.log</div></div>
  <div style="color:#888;font-size:11px;margin-top:16px;border-top:1px solid #eee;padding-top:8px">
     Aviso autom&aacute;tico de aver&iacute;a. Solo se manda a quien mantiene el
     sistema, y como mucho una vez cada 6 h.</div>
</div></body></html>""" % (_ROJO, _ROJO, _ROJO,
                           _esc(cuando or ""), _esc(mensaje),
                           _esc(servidor or "91.99.185.207"))


def cuerpo_cambios(cambios, activos, referencia):
    """Mismo contenido que el aviso de Telegram, en HTML para correo."""
    import avisos

    def ficha(r):
        # La misma linea que Telegram: grupo delante, matricula solo con
        # contrato (ver avisos.grupo_txt y avisos.matricula_txt).
        return avisos.cabecera(r, ruta_negrita=True)

    filas = []
    for c in cambios:
        r = c["reg"]
        if c["tipo"] == "NUEVO":
            color, titulo = "#0a7d00", "NUEVO ONEWAY"
            extra = ["salida %s · llegada %s" % (_esc(r["fecha_salida"]), _esc(r["fecha_llegada"]))]
            if r.get("cliente"):
                extra.append("cliente: %s" % _esc(r["cliente"]))
            tel = r.get("telefono") or r.get("telefono_conductor")
            if tel:
                extra.append("tel: %s" % _esc(tel))
            if r.get("email"):
                extra.append("email: %s" % _esc(r["email"]))
            if r.get("observaciones"):
                extra.append("obs: %s" % _esc(r["observaciones"][:150]))
        elif c["tipo"] == "EN_CURSO":
            color, titulo = "#0057b8", "ONEWAY EN CURSO — el cliente ha recogido el coche"
            extra = ["devolver en <b>%s</b> el %s" % (_esc(r["devolucion"]),
                                                      _esc(r["fecha_llegada"]))]
            if r.get("contrato"):
                extra.append("contrato %s" % _esc(r["contrato"]))
        elif c["tipo"] == "ANULADO":
            color, titulo = "#b00000", "ONEWAY ANULADO"
            extra = ["%s · salía %s" % (_esc(r.get("estado")), _esc(r.get("fecha_salida")))]
        elif c["tipo"] == "DESAPARECIDO":
            color = "#b00000"
            titulo = avisos.titulo_baja(c)
            extra = []
        else:
            color, titulo = "#b06a00", "CAMBIO"
            extra = ["%s: %s → %s" % (_esc(a), _esc(b), _esc(cc)) for a, b, cc in c["difs"]]
        filas.append(
            '<tr><td style="padding:10px 12px;border-left:4px solid %s;background:#FAFAFB">'
            '<div style="color:%s;font-weight:bold;font-size:12px">%s</div>'
            '<div style="margin-top:3px">%s</div>'
            '<div style="color:#555;font-size:12px;margin-top:3px">%s</div>'
            '</td></tr>' % (color, color, titulo, ficha(r), "<br>".join(extra)))

    return """<html><body style="font-family:Segoe UI,Arial,sans-serif;color:#222">
<div style="border-top:4px solid %s;padding-top:10px">
  <div style="font-size:18px;font-weight:bold;color:%s">AVIS · Monitor de Oneways</div>
  <div style="color:#666;font-size:13px;margin-bottom:12px">
     %d cambio(s) · %d oneway(s) activos · comparado con %s</div>
  <table style="border-collapse:separate;border-spacing:0 6px;width:100%%">%s</table>
  <div style="color:#888;font-size:11px;margin-top:16px;border-top:1px solid #eee;padding-top:8px">
     Aviso automático. Un oneway es una reserva o contrato que se entrega en una
     oficina y se devuelve en otra.</div>
</div></body></html>""" % (_ROJO, _ROJO, len(cambios), len(activos),
                           _esc(referencia or "nada previo"), "".join(filas))
