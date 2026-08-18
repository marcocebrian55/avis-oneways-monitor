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
           remitente=None, log=None):
    """Envia el aviso. Devuelve True/False y NUNCA lanza: un fallo de correo no
    debe tumbar la vigilancia."""
    try:
        if isinstance(destinatarios, str):
            destinatarios = [d.strip() for d in destinatarios.replace(";", ",").split(",")
                             if d.strip()]
        if not destinatarios:
            return False
        m = EmailMessage()
        m["Subject"] = asunto
        m["From"] = formataddr(("AVIS · Monitor de Oneways", remitente or usuario))
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


def cuerpo_cambios(cambios, activos, referencia):
    """Mismo contenido que el aviso de Telegram, en HTML para correo."""
    def ficha(r):
        return ("<b>%s %s</b> · %s · <b>%s → %s</b>"
                % (_esc(r["tipo"]), _esc(r["num"]),
                   _esc(r["matricula"] or "sin matrícula"),
                   _esc(r["salida"]), _esc(r["devolucion"])))

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
        elif c["tipo"] == "DESAPARECIDO":
            color = "#b00000"
            titulo = "ONEWAY ANULADO" if c.get("motivo") == "ANULADO" else "YA NO ES ONEWAY"
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
