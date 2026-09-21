# -*- coding: utf-8 -*-
"""
AVIS — Monitor de Oneways (Fase 1, visual)
Lee los 2 Excels de Rentway (Lista de reservas + Abiertos) de una carpeta,
detecta ONEWAYS (salida != devolución), guarda un snapshot diario y compara
con el día anterior mostrando los cambios. Interfaz con marca AVIS.
(La extracción automática de Rentway y los avisos Telegram/email se añaden encima.)
"""
import os, sys, re, glob, json, time, datetime, threading, queue
import openpyxl

# Windows o no. Los bloques de energia, DPAPI y el guardian de la escucha solo
# tienen sentido en un portatil Windows; en un servidor Linux son ruido o
# directamente revientan. Se consulta en esos sitios en vez de duplicar modulos.
ES_WINDOWS = (os.name == "nt")

# Tkinter NO es obligatorio. En un servidor headless (Debian sin python3-tk)
# este import fallaba y se llevaba por delante --desatendido y --escucha, que
# no pintan ninguna ventana: el programa moria en la linea 10, antes de leer un
# solo argumento.
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    HAY_TK = True
except Exception:                  # pragma: no cover - depende del sistema
    tk = ttk = filedialog = messagebox = None
    HAY_TK = False

VERSION = "2.5.0"
# URL del manifiesto de actualizaciones. Hoy apunta a la carpeta de OneDrive
# compartida; el dia que se publique en GitHub Releases solo cambia esta linea
# (o el fichero 'actualizacion.txt' que se pone al lado del .exe).
URL_ACTUALIZACIONES = ""

AVIS_ROJO = "#D4002B"
AVIS_ROJO_OSC = "#A80022"
GRIS = "#F4F4F4"


def resource(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def app_dir():
    """Carpeta donde vive el ESTADO: credenciales, snapshots, candados, marcas.

    En Windows es la carpeta del programa, como siempre. En el servidor eso
    seria el clon de git, y ahi el estado esta de prestado: los ficheros estan
    en .gitignore, pero basta un `git clean -fdx` para borrar el historial de
    snapshots y las credenciales. Con ONEWAYS_DATOS se separan codigo y datos,
    que es lo que permite actualizar con un `git pull` sin tocar nada mas.
    """
    d = os.environ.get("ONEWAYS_DATOS")
    if d:
        os.makedirs(d, exist_ok=True)
        return d
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ==================== MOTOR (análisis de oneways) ====================
def _leer_hoja(path, hdr_row=5):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sh = wb.active
    rows = list(sh.iter_rows(values_only=True))
    hdr = rows[hdr_row - 1]
    idx = {c: j for j, c in enumerate(hdr) if c}
    data = [r for r in rows[hdr_row:] if r and r[0] not in (None, "")]
    return idx, data


def _col(idx, r, *nombres):
    # Primero el nombre EXACTO y solo despues "que lo contenga". Con el grupo
    # hacia falta: en Abiertos "Grupo" existe tal cual, pero en Reservas hay
    # "Grupo solicitado" e "ID de grupo", y buscando por trozos se cogeria la
    # primera que aparezca por orden de columnas, que no es un criterio.
    for name in nombres:
        for k in idx:
            if k and name.strip().lower() == str(k).strip().lower():
                return r[idx[k]]
    for name in nombres:
        for k in idx:
            if k and name.lower() in str(k).lower():
                return r[idx[k]]
    return None


def _norm(v):
    return str(v).strip() if v not in (None, "") else ""


def _oficina_id(v, solo_codigo=False):
    """Codigo de la oficina TAL CUAL lo da Rentway, espacios incluidos.

    Hay codigos con espacio: 'TFN BUD', 'FUE BUD', 'FUE TUR'. Quedarse con la
    primera palabra, como se hacia hasta el 21/09/2026, convertia 'TFN BUD' en
    'TFN', que es OTRA oficina (la de AVIS): un TFN BUD -> TFSBUD salia como
    TFN -> TFSBUD, y un TFN BUD -> TFN no salia, porque parecia la misma.

    `solo_codigo`: la celda trae solo el codigo (columna "ID de estacion" de
    Reservas) y se toma entera. Si no, trae 'codigo nombre' ('TFN BUD Apt
    Tenerife Norte BUDGET', en Abiertos) y el codigo es el trozo inicial mas
    largo que exista en el catalogo de oficinas; si no hay ninguno, la primera
    palabra, como antes.
    """
    palabras = _norm(v).split()
    if not palabras:
        return ""
    if solo_codigo:
        return " ".join(palabras)
    mapa = mapa_islas()
    for n in range(len(palabras), 1, -1):
        if " ".join(palabras[:n]) in mapa:
            return " ".join(palabras[:n])
    return palabras[0]


def _fecha(v):
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%d/%m/%Y %H:%M")
    return _norm(v)


def _matricula(v):
    """De 'Special reservation - 1324LXK' o '1324LXK' saca la matrícula."""
    s = _norm(v)
    if " - " in s:
        s = s.split(" - ")[-1].strip()
    return s


def leer_oneways(reservas_path, abiertos_path, no_oneway=None):
    """Lee los dos informes base y devuelve {clave: oneway}.

    `no_oneway`, si se pasa un set, recoge las claves cuyo CONTRATO dice que se
    devuelve en la misma oficina de la que salio. Hace falta para distinguir,
    cuando un oneway desaparece, "le han cambiado la devolucion" (se avisa) de
    "el contrato se ha cerrado" (no se avisa): en los dos casos la clave
    simplemente deja de estar.
    """
    ow = {}
    if reservas_path and os.path.exists(reservas_path):
        idx, data = _leer_hoja(reservas_path)
        for r in data:
            sal_id = _oficina_id(_col(idx, r, "ID de estación de salida", "ID de estacion de salida"), solo_codigo=True)
            dev_id = _oficina_id(_col(idx, r, "ID de estación de devolucion", "ID de estación de devolución", "ID de estacion de devolucion"), solo_codigo=True)
            if not (sal_id and dev_id) or sal_id == dev_id:
                continue
            num = _norm(_col(idx, r, "N.º Reserva", "Reserva"))
            estado = _norm(_col(idx, r, "Estado"))
            elim = _norm(_col(idx, r, "Eliminado"))
            activo = (elim.lower() != "true") and ("cancel" not in estado.lower())
            ow["RES-" + num] = {
                "tipo": "Reserva", "num": num,
                "matricula": _matricula(_col(idx, r, "Número de matrícula", "Numero de matricula")),
                # GRUPO RESERVADO (pedido por las oficinas el 17/09/2026: "es
                # mas importante el grupo que la matricula"). "ID de grupo" es el
                # grupo que tiene la reserva; "Grupo solicitado" el que pidio el
                # cliente. Coinciden en 2.914 de 2.922 reservas (medido ese dia).
                "grupo": _norm(_col(idx, r, "ID de grupo")),
                "grupo_solicitado": _norm(_col(idx, r, "Grupo solicitado")),
                "salida": sal_id, "devolucion": dev_id, "codigo_entero": True,
                "fecha_salida": _fecha(_col(idx, r, "Fecha de salida")),
                "fecha_llegada": _fecha(_col(idx, r, "Fecha llegada", "Fecha de llegada")),
                "cliente": _norm(_col(idx, r, "Nombre del cliente")),
                "estado": estado, "activo": activo,
            }
    if abiertos_path and os.path.exists(abiertos_path):
        idx2, data2 = _leer_hoja(abiertos_path)
        for r in data2:
            # OJO CON EL NOMBRE DE LA COLUMNA. El informe de Abiertos cambio de
            # formato y la oficina de salida paso de "ID de la oficina" a
            # "Oficina de salida". _col devuelve None cuando no la encuentra, o
            # sea que sal_id quedaba vacio y el descarte de abajo se comia TODAS
            # las filas: el lado de contratos llevaba muerto en silencio desde
            # entonces (medido el 26/08/2026: 0 oneways de contrato, siempre).
            # Se aceptan los dos nombres para que el proximo cambio de formato
            # no lo vuelva a matar sin decir nada.
            sal_id = _oficina_id(_col(idx2, r, "Oficina de salida", "ID de la oficina"))
            dev_id = _oficina_id(_col(idx2, r, "Oficina de devolución", "Oficina de devolucion"))
            num = _norm(_col(idx2, r, "N.º Contrato", "Contrato"))
            num_res = _norm(_col(idx2, r, "N.º Reserva", "Reserva"))
            clave_res = ("RES-" + num_res) if num_res else None

            # Si falta cualquiera de las dos oficinas no se sabe si es oneway.
            # No decidir es lo correcto: dar por hecho que NO lo es daria de baja
            # oneways vivos por un hueco en los datos.
            if not (sal_id and dev_id):
                continue

            if sal_id == dev_id:
                # El contrato manda sobre la reserva: si al recoger el coche se
                # devuelve a la misma oficina, ya no es oneway aunque la reserva
                # siga diciendo lo contrario. Sale de la lista y eso genera su
                # baja, que es exactamente lo que ha pasado.
                if clave_res and clave_res in ow:
                    del ow[clave_res]
                if no_oneway is not None:
                    no_oneway.add(clave_res or ("CON-" + num))
                continue

            datos = {
                "matricula": _matricula(_col(idx2, r, "Número de matrícula", "Numero de matricula")),
                # El "Grupo" de Abiertos es el del COCHE entregado, no el
                # reservado: medido el 17/09/2026, coches de grupo SC salen
                # cobrados como Mini, Economic 1 o Economic 4. Por eso va en un
                # campo aparte y no pisa "grupo".
                "grupo_coche": _norm(_col(idx2, r, "Grupo")),
                "salida": sal_id, "devolucion": dev_id, "codigo_entero": True,
                "fecha_salida": _fecha(_col(idx2, r, "Fecha de salida")),
                "fecha_llegada": _fecha(_col(idx2, r, "Fecha de regreso", "Fecha de retorno")),
                "cliente": _norm(_col(idx2, r, "Nombre del cliente")),
                "estado": "En curso", "activo": True, "contrato": num,
            }

            if clave_res and clave_res in ow:
                # LA MISMA RESERVA, YA RECOGIDA: se fusiona en su clave RES- en
                # vez de crear una CON- nueva. Si se creara, un solo coche
                # saliendo del mostrador produciria dos avisos que se contradicen
                # ("NUEVO ONEWAY" por el contrato y "YA NO ES ONEWAY" por la
                # reserva) y contaria dos veces en el total de activos.
                # Los datos del contrato pisan a los de la reserva porque son los
                # reales: matricula asignada y fechas de verdad, no las previstas.
                puestos = [k for k, v in datos.items() if v not in (None, "")]
                ow[clave_res].update({k: datos[k] for k in puestos})
                # Se apunta QUE campos ha puesto el contrato. Sirve para poder
                # recuperarlos tal cual las pasadas en que el informe de Abiertos
                # no baje (ver arrastrar_contratos): sin esta lista habria que
                # adivinar cuales eran, y adivinar mal significa avisar de un
                # cambio que no ha existido.
                ow[clave_res]["_de_contrato"] = puestos
            elif clave_res:
                # Contrato con reserva que HOY no esta entre los oneways: o su
                # reserva no era oneway (le cambiaron la devolucion al recoger) o
                # ya salio de la ventana de fechas del informe de reservas, que es
                # lo normal a partir del dia siguiente a la recogida.
                #
                # Se guarda con la clave de la RESERVA, no con CON-. Si no, el
                # mismo coche cambiaria de clave a medianoche (RES-900 ayer,
                # CON-590 hoy) y eso son dos avisos falsos: una baja y un nuevo.
                ow[clave_res] = dict(datos, tipo="Reserva", num=num_res,
                                     _de_contrato=list(datos))
            else:
                # Contrato sin reserva (alquiler de mostrador): hay un coche
                # cruzando islas que hay que vigilar igual.
                ow["CON-" + num] = dict(datos, tipo="Contrato", num=num,
                                        _de_contrato=list(datos))
    return ow


def inicio_ventana(ahora=None):
    """Primer instante que cubre el informe de reservas: hoy a las 00:00.

    Tiene que cuadrar con `rentway_export.descargar_informes`, que pide las
    reservas desde hoy a las 00:00. Lo que salio antes ya no aparece en ese
    informe, y que no aparezca NO significa que haya dejado de ser oneway.
    """
    ahora = ahora or datetime.datetime.now()
    return ahora.replace(hour=0, minute=0, second=0, microsecond=0)


def _antes_de(fecha_txt, instante):
    """¿La fecha 'DD/MM/YYYY HH:MM' de un oneway es anterior al instante?
    Una fecha que no se entiende NO es anterior: ante la duda no se decide."""
    try:
        return datetime.datetime.strptime(str(fecha_txt), "%d/%m/%Y %H:%M") < instante
    except Exception:
        return False


def conservar_conocidos(ow, ayer, campos=("grupo", "grupo_solicitado")):
    """Un grupo que hoy llega VACIO se toma de la pasada anterior.

    Los oneways que solo se ven por su contrato sacan el grupo del informe
    ampliado de reservas (2119), que es opcional y puede fallar. Sin esto, cada
    fallo de ese informe seria un aviso "grupo: SC -> (vacio)" a las oficinas.
    """
    for clave, reg in ow.items():
        previo = (ayer or {}).get(clave) or {}
        for c in campos:
            if not reg.get(c) and previo.get(c):
                reg[c] = previo[c]


def arrastrar_contratos(ow, ayer, log=None):
    """Sin el informe de Abiertos, conserva lo ULTIMO que se supo de contratos.

    POR QUE HACE FALTA: hasta el 26/08/2026 quedarse sin ese informe daba igual,
    porque el lado de contratos estaba roto y no aportaba nada. Ahora que
    funciona, hay tres caminos y dos son malos:

      1. Reutilizar el open_*.xlsx de otra pasada. Es lo que hacia
         encontrar_excels() sin decirlo, porque coge el mas reciente de
         Downloads. Un contrato cerrado de madrugada sigue figurando abierto.
      2. Ignorar los contratos. Entonces los oneways ya recogidos pierden su
         contrato, el estado vuelve de "En curso" al de la reserva y sale un
         aviso de cambio que no ha ocurrido -- a 28 personas, de madrugada.
      3. Esta: arrastrar lo ultimo conocido y NO inventar cambios.

    Con el informe colgandose cinco pasadas por noche, la 1 y la 2 harian
    oscilar el sistema hasta las 08:00. Aqui no se avisa de nada porque, en
    honor a la verdad, no se ha visto nada nuevo.
    """
    if not ayer:
        return 0
    inicio = inicio_ventana()
    arrastrados = 0
    for clave, previo in ayer.items():
        campos = previo.get("_de_contrato")
        if not campos:
            continue                      # nunca tuvo contrato: nada que arrastrar
        if clave not in ow:
            # Hoy no se ve. Solo se recupera si su reserva NO PODIA verse: el
            # coche salio antes de hoy y la reserva ya no entra en la ventana del
            # informe de reservas (desde el 17/09/2026 esos oneways se sostienen
            # solo por su contrato). Si salio hoy, la reserva deberia estar; si
            # no esta es que la han quitado, y eso no se tapa.
            if clave.startswith("CON-") or _antes_de(previo.get("fecha_salida"), inicio):
                ow[clave] = dict(previo)
                arrastrados += 1
        else:                             # reserva ya recogida: devolverle lo suyo
            for campo in campos:
                if previo.get(campo) not in (None, ""):
                    ow[clave][campo] = previo[campo]
            ow[clave]["_de_contrato"] = campos
            arrastrados += 1
    if arrastrados and log:
        log("  Sin informe de Abiertos: conservo lo ultimo conocido de %d "
            "contrato(s). No se compara contra datos viejos ni se inventan cambios."
            % arrastrados)
    return arrastrados


# ---------- datos ampliados (informes de enriquecimiento) ----------
def leer_detalle(path):
    """Informe 2119 'Reservas por Oficina de recogida': datos extra por N.º Reserva
    (vuelo, franquicia, coberturas...). Devuelve {num_reserva: {...}}."""
    if not path or not os.path.exists(path):
        return {}
    idx, data = _leer_hoja(path)
    out = {}
    for r in data:
        num = _norm(_col(idx, r, "N.º Reserva"))
        if not num:
            continue
        out[num] = {
            "vuelo": _norm(_col(idx, r, "Vuelo salida")),
            "lugar_entrega": _norm(_col(idx, r, "Lugar de entrega")),
            "observaciones": _norm(_col(idx, r, "Observaciones")),
            "extras": _norm(_col(idx, r, "Extras")),
            "cdw": _norm(_col(idx, r, "CDW")),
            "tp": _norm(_col(idx, r, "TP")),
            "pai": _norm(_col(idx, r, "PAI")),
            "franquicia": _norm(_col(idx, r, "Franquicia")),
            "conductor_adicional": _norm(_col(idx, r, "Conductor adicional")),
            # De aqui sale el grupo de los oneways que ya no estan en el
            # informe de reservas (ver enriquecer): este informe mira 60 dias
            # hacia atras, el de reservas solo desde hoy.
            "grupo": _norm(_col(idx, r, "ID de grupo")),
            "grupo_solicitado": _norm(_col(idx, r, "Grupo solicitado")),
        }
    return out


def leer_anulados(path):
    """Informe 2092 'Anulados': {n.º contrato: fecha de salida}. Sirve para saber
    si un oneway que desaparece fue ANULADO o simplemente terminó."""
    if not path or not os.path.exists(path):
        return {}
    idx, data = _leer_hoja(path)
    out = {}
    for r in data:
        num = _norm(_col(idx, r, "Contrato de alquiler"))
        if num:
            out[num] = _fecha(_col(idx, r, "Fecha de salida"))
    return out


def leer_contactos(path_res, path_con):
    """Informes 2162 / 2163: correo y teléfono de cliente y conductor,
    indexados por la misma clave que los oneways (RES-<n> / CON-<n>)."""
    out = {}
    for path, pref, campo in ((path_res, "RES-", "N.º Reserva"),
                              (path_con, "CON-", "Contrato de alquiler")):
        if not path or not os.path.exists(path):
            continue
        idx, data = _leer_hoja(path)
        for r in data:
            num = _norm(_col(idx, r, campo))
            if not num:
                continue
            out[pref + num] = {
                "email": _norm(_col(idx, r, "Correo electrónico del cliente")),
                "telefono": _norm(_col(idx, r, "Teléfono del cliente")),
                "email_conductor": _norm(_col(idx, r, "Correo electrónico del conductor")),
                "telefono_conductor": _norm(_col(idx, r, "Teléfono del conductor")),
            }
    return out


CAMPOS_EXTRA = ["vuelo", "lugar_entrega", "observaciones", "extras", "cdw", "tp",
                "pai", "franquicia", "conductor_adicional",
                "email", "telefono", "email_conductor", "telefono_conductor"]


def enriquecer(ow, fich):
    """Añade a cada oneway los datos ampliados y de contacto (si hay ficheros)."""
    detalle = leer_detalle(fich.get("detalle"))
    contactos = leer_contactos(fich.get("contacto_res"), fich.get("contacto_con"))
    for clave, reg in ow.items():
        for c in CAMPOS_EXTRA:
            reg.setdefault(c, "")
        if clave.startswith("RES-"):
            extra = dict(detalle.get(clave[4:], {}))
            # El grupo del informe de reservas manda; el del detalle solo
            # rellena huecos (oneways que se ven solo por su contrato).
            for c in ("grupo", "grupo_solicitado"):
                v = extra.pop(c, "")
                if v and not reg.get(c):
                    reg[c] = v
            reg.update(extra)
        reg.update(contactos.get(clave, {}))
    return ow


_MAPA_GRUPOS = None


def descripcion_grupo(codigo):
    """'SC' -> 'Economic 4'. Tabla en grupos.json, sacada del informe 2162 de
    Rentway (ID de grupo <-> Tarifa, sin una sola contradiccion en 3.000
    reservas). Un grupo que no este devuelve '': se muestra solo el codigo."""
    global _MAPA_GRUPOS
    if _MAPA_GRUPOS is None:
        try:
            with open(resource("grupos.json"), encoding="utf-8") as f:
                _MAPA_GRUPOS = json.load(f)
        except Exception:
            _MAPA_GRUPOS = {}
    return _MAPA_GRUPOS.get(str(codigo or "").strip(), "")


# Solo estos campos disparan aviso de CAMBIO. Los de CAMPOS_EXTRA quedan fuera
# a propósito: son contexto, y cambian solos (p.ej. se rellena el vuelo).
CAMPOS_VIGILADOS = ["grupo", "matricula", "salida", "devolucion", "fecha_salida",
                    "fecha_llegada", "estado", "activo"]


def completar_grupos(ow):
    """Pone la descripcion del grupo reservado ('SC' -> 'Economic 4')."""
    for reg in ow.values():
        reg["grupo_desc"] = descripcion_grupo(reg.get("grupo"))
    return ow


def _recogido(antes, ahora):
    """¿El cliente acaba de recoger el coche? (la reserva ya tiene contrato)

    Dos senales, porque una sola no basta:
      - Aparece numero de contrato. Es la buena, pero depende de que el informe
        de Abiertos haya bajado, y ese se cuelga de madrugada.
      - El estado de la reserva pasa a "Confirmed with RA" (RA = Rental
        Agreement). Lo dice el propio informe de reservas, asi que funciona
        aunque falte el de Abiertos.
    """
    if not antes.get("contrato") and ahora.get("contrato"):
        return True
    return ("with ra" not in str(antes.get("estado") or "").lower()
            and "with ra" in str(ahora.get("estado") or "").lower())


def _difs(antes, ahora):
    """Campos vigilados que han cambiado de verdad."""
    difs = []
    for c in CAMPOS_VIGILADOS:
        if c not in antes:
            # La foto anterior no tenia ese campo (se añadio al programa
            # despues, como el grupo el 17/09/2026). No es un cambio: sin esta
            # regla, el primer despliegue avisaria de TODOS los oneways vivos.
            continue
        viejo, nuevo = antes.get(c), ahora.get(c)
        if str(viejo) == str(nuevo):
            continue
        if (c in ("salida", "devolucion") and not antes.get("codigo_entero")
                and str(nuevo).split()[:1] == [str(viejo)]):
            # La foto es de antes del 21/09/2026 y guardaba la oficina cortada
            # ('TFN' por 'TFN BUD', ver _oficina_id). No ha cambiado nada: la
            # oficina es la misma, solo que ahora se lee bien. Sin esta regla,
            # el primer despliegue avisaria de todos los oneways de esas
            # oficinas. Deja de aplicar en cuanto se guarda la primera foto nueva.
            continue
        if c == "matricula" and not ahora.get("contrato"):
            # Antes de la entrega la matricula es una PRE-asignacion y cambia
            # sola (medido: 8 avisos "matricula: '' -> 5008NFG" sin que nadie
            # hubiera recogido nada). A las oficinas les importa cuando ya hay
            # contrato, y entonces sale en el aviso de EN CURSO.
            continue
        difs.append((c, viejo, nuevo))
    return difs


def comparar(hoy, ayer, anulados=None, no_oneway=None, inicio=None, log=None,
             silenciosos=None):
    """Lista de cambios QUE HAY QUE AVISAR entre dos fotos.

    Lo que cambia pero no merece aviso se deja en el log (si se pasa `log`) y
    no se devuelve. Repasando las 321 fotos del 24/08 al 17/09/2026, 65 de los
    avisos enviados eran de ese tipo; estas reglas son las que los separan.

    `silenciosos`, si se pasa una lista, recoge los CIERRES que no se avisan
    ({"reg", "motivo"}: TERMINADO o SIN_RECOGER). No van al correo, pero la
    hoja de Google los necesita para pasarlos a Completados.
    """
    anulados = anulados or {}
    no_oneway = no_oneway or set()
    inicio = inicio or inicio_ventana()
    log = log or (lambda m: None)
    silenciosos = silenciosos if silenciosos is not None else []
    cambios = []
    for clave, reg in hoy.items():
        if clave not in ayer:
            if not reg.get("activo"):
                # Una reserva YA ANULADA que entra en la ventana de 7 dias. Se
                # anunciaba como "NUEVO ONEWAY" un coche que no va a salir
                # (5 veces entre el 07 y el 12/09/2026).
                log("  (sin aviso) %s aparece ya anulada: %s" % (clave, reg.get("estado")))
                continue
            cambios.append({"tipo": "NUEVO", "reg": reg, "difs": [], "motivo": ""})
            continue
        antes = ayer[clave]
        difs = _difs(antes, reg)
        if not difs:
            continue
        if antes.get("activo") and not reg.get("activo"):
            # Anulada o eliminada. Llegaba como "estado: Confirmed -> Canceled
            # by Operator / activo: True -> False", que hay que saber leer.
            tipo = "ANULADO"
        elif _recogido(antes, reg):
            # La recogida se cuenta aparte de un CAMBIO cualquiera: es el
            # momento en que el coche SALE, y en un oneway eso es justo lo
            # que le importa a la oficina de destino. Antes llegaba como
            # "estado: Confirmed -> Confirmed with RA", que no le dice
            # absolutamente nada a nadie en un mostrador.
            tipo = "EN_CURSO"
        else:
            tipo = "CAMBIO"
        cambios.append({"tipo": tipo, "reg": reg, "difs": difs, "motivo": ""})

    for clave, reg in ayer.items():
        if clave in hoy:
            continue
        contrato = reg.get("contrato") or (reg.get("num") if clave.startswith("CON-") else "")
        if contrato and contrato in anulados:
            cambios.append({"tipo": "DESAPARECIDO", "reg": reg, "difs": [], "motivo": "ANULADO"})
        elif clave in no_oneway:
            # El contrato dice ahora que se devuelve donde salio.
            cambios.append({"tipo": "DESAPARECIDO", "reg": reg, "difs": [], "motivo": "MISMA_OFICINA"})
        elif not reg.get("activo"):
            # Ya se aviso de la anulacion cuando ocurrio; ahora solo sale de
            # la ventana de fechas (12 avisos repetidos hasta el 17/09/2026).
            log("  (sin aviso) %s anulada sale de la ventana" % clave)
        elif reg.get("contrato"):
            # El informe de Abiertos (pedido desde 60 dias atras) ya no trae su
            # contrato: se ha cerrado, el coche esta devuelto. Si Abiertos no
            # hubiera bajado, arrastrar_contratos lo habria conservado.
            log("  (sin aviso) %s terminado: contrato %s cerrado" % (clave, reg.get("contrato")))
            silenciosos.append({"reg": reg, "motivo": "TERMINADO"})
        elif _antes_de(reg.get("fecha_salida"), inicio):
            # Su fecha de salida ya paso y la reserva salio de la ventana del
            # informe. Es LA trampa de medianoche: la Reserva 900 se anuncio
            # como "YA NO ES ONEWAY" a 28 personas el 26/08/2026 a las 00:08.
            log("  (sin aviso) %s sale de la ventana de fechas (salida %s)"
                % (clave, reg.get("fecha_salida")))
            silenciosos.append({"reg": reg, "motivo": "SIN_RECOGER"})
        else:
            cambios.append({"tipo": "DESAPARECIDO", "reg": reg, "difs": [], "motivo": ""})
    return cambios


def registrar(msg):
    """Traza a fichero: imprescindible en el .exe (sin consola) y para el
    futuro modo desatendido."""
    try:
        with open(os.path.join(app_dir(), "avis_oneways.log"), "a", encoding="utf-8") as f:
            f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S ") + str(msg) + "\n")
    except Exception:
        pass


def carpeta_snapshots():
    d = os.path.join(app_dir(), "snapshots_oneways")
    os.makedirs(d, exist_ok=True)
    return d


def guardar_snapshot(ow):
    """Una foto POR PASADA, con hora.

    Antes era una por día y se comparaba contra la del día anterior. Al pasar a
    revisar cada 2 horas eso no valía: las pasadas del mismo día se pisaban y
    nunca se veía un cambio intradía.
    """
    sello = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    with open(os.path.join(carpeta_snapshots(), f"snapshot_{sello}.json"), "w", encoding="utf-8") as f:
        json.dump(ow, f, ensure_ascii=False, indent=1)
    _limpiar_snapshots()


def _limpiar_snapshots(maximo=400):
    """Con 12 pasadas al día conviene no acumular sin fin."""
    files = sorted(glob.glob(os.path.join(carpeta_snapshots(), "snapshot_*.json")))
    for f in files[:-maximo]:
        try:
            os.remove(f)
        except Exception:
            pass


def cargar_snapshot_anterior():
    """La foto de la ÚLTIMA pasada (la que sea). Se llama ANTES de guardar la
    de ahora, así que la más reciente en disco es siempre la anterior."""
    files = sorted(glob.glob(os.path.join(carpeta_snapshots(), "snapshot_*.json")))
    if not files:
        return None, None
    with open(files[-1], encoding="utf-8") as f:
        etiqueta = os.path.basename(files[-1])[9:-5].replace("_", " ")
        return json.load(f), etiqueta


# Nombre con el que Rentway descarga cada informe (ver rentway_export.py)
PATRONES_EXCEL = {
    "reservas":     "reservations_list_*.xlsx",              # 2126 (base)
    "abiertos":     "open_*.xlsx",                           # 2094 (base)
    "detalle":      "reservations_by_station out_*.xlsx",    # 2119 (ampliado)
    "anulados":     "deleted_*.xlsx",                        # 2092 (ampliado)
    "contacto_res": "reservation_information_*.xlsx",        # 2162 (ampliado)
    "contacto_con": "rental_agreements_information_*.xlsx",  # 2163 (ampliado)
}


# Columnas de las que VIVE el programa, tal como las escribe Rentway v5.26
# (comprobadas el 17/09/2026). Si una desaparece o cambia de nombre hay que
# enterarse ESE DIA. Paso de verdad: "ID de la oficina" se renombro a "Oficina
# de salida" en Abiertos y el lado de contratos estuvo semanas descartando todas
# las filas sin decir nada, porque descartar filas en silencio es
# indistinguible de que no haya filas.
COLUMNAS_ESPERADAS = {
    "reservas": ["N.º Reserva", "ID de estación de salida", "ID de estación de devolucion",
                 "Número de matrícula", "Fecha de salida", "Fecha llegada", "Estado",
                 "Eliminado", "Nombre del cliente", "ID de grupo", "Grupo solicitado"],
    "abiertos": ["N.º Contrato", "N.º Reserva", "Número de matrícula", "Grupo",
                 "Nombre del cliente", "Fecha de salida", "Oficina de salida",
                 "Fecha de regreso", "Oficina de devolución"],
    "detalle": ["N.º Reserva", "Vuelo salida", "Lugar de entrega", "Observaciones",
                "ID de grupo", "Grupo solicitado"],
    "anulados": ["Contrato de alquiler", "Fecha de salida"],
    "contacto_res": ["N.º Reserva", "Correo electrónico del cliente", "Teléfono del cliente",
                     "Correo electrónico del conductor", "Teléfono del conductor"],
    "contacto_con": ["Contrato de alquiler", "Correo electrónico del cliente",
                     "Teléfono del cliente", "Correo electrónico del conductor",
                     "Teléfono del conductor"],
}


def comprobar_formato(fich):
    """Devuelve una lista de problemas de formato ('' si todo cuadra).

    Compara por nombre EXACTO (sin mayusculas ni espacios de sobra): un
    renombrado es justo lo que hay que cazar, aunque _col lo tolerase.
    """
    problemas = []
    for clave, esperadas in COLUMNAS_ESPERADAS.items():
        ruta = (fich or {}).get(clave)
        if not ruta or not os.path.exists(ruta):
            continue                     # no bajado: eso se avisa por otro lado
        try:
            wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
            cab = next(wb.active.iter_rows(min_row=5, max_row=5, values_only=True), ())
            wb.close()
        except Exception as e:
            problemas.append("%s: no se pudo leer (%s)" % (clave, str(e)[:80]))
            continue
        hay = {str(c).strip().lower() for c in cab if c not in (None, "")}
        faltan = [c for c in esperadas if c.strip().lower() not in hay]
        if faltan:
            problemas.append("%s (%s): faltan %s" % (clave, os.path.basename(ruta),
                                                    ", ".join(faltan)))
    return problemas


def encontrar_excels(carpeta):
    """Devuelve {clave: ruta_del_mas_reciente_o_None} para los 6 informes."""
    def ultimo(patron):
        fs = glob.glob(os.path.join(carpeta, patron))
        return max(fs, key=os.path.getmtime) if fs else None
    return {k: ultimo(v) for k, v in PATRONES_EXCEL.items()}


# ==================== INTERFAZ (marca AVIS) ====================
class App:
    def __init__(self, root):
        self.root = root
        root.title("AVIS — Monitor de Oneways")
        root.geometry("1180x680")
        root.configure(bg="white")
        self._estilo()

        # ---- Cabecera con logo AVIS ----
        header = tk.Frame(root, bg="white")
        header.pack(fill="x", side="top")
        try:
            self.logo = tk.PhotoImage(file=resource(os.path.join("assets", "avis_banner.png"))).subsample(3, 3)
            tk.Label(header, image=self.logo, bg="white").pack(side="left", padx=16, pady=10)
        except Exception:
            tk.Label(header, text="AVIS", bg="white", fg=AVIS_ROJO,
                     font=("Arial Black", 28, "bold")).pack(side="left", padx=16, pady=10)
        tk.Label(header, text="Monitor de Oneways", bg="white", fg="#222",
                 font=("Segoe UI", 18, "bold")).pack(side="left", padx=6)
        tk.Frame(root, bg=AVIS_ROJO, height=4).pack(fill="x")

        # ---- Barra de acciones (UNA sola: lo de configurar va aparte) ----
        bar = tk.Frame(root, bg=GRIS)
        bar.pack(fill="x")
        interior = tk.Frame(bar, bg=GRIS)
        interior.pack(fill="x", padx=14, pady=9)

        tk.Label(interior, text="Carpeta de datos", bg=GRIS, fg="#5A5A60",
                 font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w")
        self.dir_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Downloads"))
        tk.Entry(interior, textvariable=self.dir_var, width=44, relief="solid", bd=1,
                 font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", ipady=3)
        ttk.Button(interior, text="Elegir…", command=self.elegir,
                   width=8).grid(row=1, column=1, padx=(6, 18))

        tk.Label(interior, text="Previsión", bg=GRIS, fg="#5A5A60",
                 font=("Segoe UI", 8)).grid(row=0, column=2, sticky="w")
        marco_dias = tk.Frame(interior, bg=GRIS)
        marco_dias.grid(row=1, column=2, sticky="w")
        self.dias_var = tk.StringVar(value="7")
        tk.Spinbox(marco_dias, from_=1, to=60, width=3, textvariable=self.dias_var,
                   relief="solid", bd=1, font=("Segoe UI", 9)).pack(side="left", ipady=2)
        tk.Label(marco_dias, text="días", bg=GRIS, fg="#5A5A60",
                 font=("Segoe UI", 9)).pack(side="left", padx=(4, 0))

        self.ampliado_var = tk.BooleanVar(value=True)
        tk.Checkbutton(interior, text="Datos ampliados", variable=self.ampliado_var,
                       bg=GRIS, activebackground=GRIS, font=("Segoe UI", 9),
                       fg="#3A3A40").grid(row=1, column=3, padx=(18, 0), sticky="w")

        acciones = tk.Frame(interior, bg=GRIS)
        acciones.grid(row=1, column=4, sticky="e")
        interior.columnconfigure(4, weight=1)
        self.btn_bajar = ttk.Button(acciones, text="Descargar de Rentway y analizar",
                                    style="Avis.TButton", command=self.descargar)
        self.btn_bajar.pack(side="left")
        ttk.Button(acciones, text="Analizar ahora", command=self.analizar).pack(side="left", padx=6)
        ttk.Button(acciones, text="⚙  Configuración",
                   command=self.abrir_configuracion).pack(side="left")

        # variables de configuracion (los campos viven en el dialogo, no en la
        # pantalla principal: el token no debe estar a la vista)
        self.user_var = tk.StringVar()
        self.pass_var = tk.StringVar()
        self.info_cred = tk.StringVar(value="")
        self.tg_token = tk.StringVar()
        self.tg_chat = tk.StringVar()
        self.info_tg = tk.StringVar(value="")
        self.co_serv = tk.StringVar()
        self.co_puerto = tk.StringVar(value="587")
        self.co_user = tk.StringVar()
        self.co_pass = tk.StringVar()
        self.co_remit = tk.StringVar()
        self.co_dest = tk.StringVar()
        self.info_co = tk.StringVar(value="")
        self.info_act = tk.StringVar(value="")

        self.cola = queue.Queue()
        self.worker = None
        self._estado_credenciales()
        self._estado_telegram()
        self._estado_correo()
        self._avisar_si_otra_instancia()
        root.after(300, self._poll)

        # ---- Cuerpo: oneways (arriba) + cambios (abajo) ----
        cuerpo = tk.PanedWindow(root, orient="vertical", bg="white", sashwidth=8,
                                bd=0, sashrelief="flat")
        cuerpo.pack(fill="both", expand=True, padx=14, pady=(12, 6))

        f1 = tk.Frame(cuerpo, bg="white")
        cab1 = tk.Frame(f1, bg="white")
        cab1.pack(fill="x")
        tk.Label(cab1, text="ONEWAYS ACTIVOS", bg="white", fg=AVIS_ROJO,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        self.lbl_cuenta = tk.Label(cab1, text="", bg="white", fg="#8A8A90",
                                   font=("Segoe UI", 9))
        self.lbl_cuenta.pack(side="left", padx=8)
        tk.Frame(f1, bg="#E3E3E6", height=1).pack(fill="x", pady=(4, 6))

        cols = ("tipo", "num", "grupo", "matricula", "ruta", "salida_f", "llegada_f", "estado",
                "cliente", "vuelo", "contacto")
        marco_tv = tk.Frame(f1, bg="white")
        marco_tv.pack(fill="both", expand=True)
        self.tv = ttk.Treeview(marco_tv, columns=cols, show="headings", height=9,
                               style="Avis.Treeview")
        scr = ttk.Scrollbar(marco_tv, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=scr.set)
        for c, txt, w in [("tipo", "Tipo", 70), ("num", "Nº", 55), ("grupo", "Grupo", 60),
                          ("matricula", "Matrícula", 90),
                          ("ruta", "Ruta", 110), ("salida_f", "Salida", 125),
                          ("llegada_f", "Llegada", 125), ("estado", "Estado", 110),
                          ("cliente", "Cliente", 150), ("vuelo", "Vuelo", 70),
                          ("contacto", "Teléfono", 115)]:
            self.tv.heading(c, text=txt)
            self.tv.column(c, width=w, anchor="w")
        self.tv.tag_configure("par", background="#FAFAFB")
        self.tv.pack(side="left", fill="both", expand=True)
        scr.pack(side="right", fill="y")
        cuerpo.add(f1)

        f2 = tk.Frame(cuerpo, bg="white")
        cab2 = tk.Frame(f2, bg="white")
        cab2.pack(fill="x")
        tk.Label(cab2, text="CAMBIOS DESDE LA PASADA ANTERIOR", bg="white", fg=AVIS_ROJO,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Frame(f2, bg="#E3E3E6", height=1).pack(fill="x", pady=(4, 6))
        self.txt = tk.Text(f2, height=8, wrap="word", font=("Consolas", 9),
                           relief="flat", bg="#FCFCFD", padx=8, pady=6,
                           highlightthickness=1, highlightbackground="#E3E3E6")
        self.txt.pack(fill="both", expand=True)
        self.txt.tag_configure("NUEVO", foreground="#0a7d00")
        self.txt.tag_configure("DESAP", foreground="#b00000")
        self.txt.tag_configure("CAMBIO", foreground="#b06a00")
        cuerpo.add(f2)

        # ---- Barra de progreso (solo visible mientras trabaja) ----
        self.marco_prog = tk.Frame(root, bg="white")
        self.lbl_prog = tk.Label(self.marco_prog, text="", bg="white", fg="#3A3A40",
                                 font=("Segoe UI", 9), anchor="w")
        self.lbl_prog.pack(fill="x", padx=14)
        self.prog = ttk.Progressbar(self.marco_prog, style="Avis.Horizontal.TProgressbar",
                                    mode="determinate", maximum=100)
        self.prog.pack(fill="x", padx=14, pady=(2, 8))

        # ---- Barra de estado (abajo, como en cualquier aplicación) ----
        pie = tk.Frame(root, bg="#F0F0F2")
        pie.pack(fill="x", side="bottom")
        tk.Frame(pie, bg="#E3E3E6", height=1).pack(fill="x")
        self.estado = tk.StringVar(value="Listo.")
        tk.Label(pie, textvariable=self.estado, bg="#F0F0F2", fg="#3A3A40",
                 font=("Segoe UI", 9), anchor="w").pack(side="left", padx=14, pady=5)
        tk.Label(pie, text="v" + VERSION, bg="#F0F0F2", fg="#9A9AA0",
                 font=("Segoe UI", 8)).pack(side="right", padx=(6, 14))
        self.lbl_avisos = tk.Label(pie, text="", bg="#F0F0F2", fg="#6A6A70",
                                   font=("Segoe UI", 9))
        self.lbl_avisos.pack(side="right")

    def _estilo(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("Avis.TButton", background=AVIS_ROJO, foreground="white",
                     font=("Segoe UI", 9, "bold"), padding=(14, 6), borderwidth=0)
        st.map("Avis.TButton", background=[("active", AVIS_ROJO_OSC),
                                           ("disabled", "#D9A3AE")])
        st.configure("TButton", font=("Segoe UI", 9), padding=(10, 6))
        # tabla: mas aire entre filas y cabecera sobria
        st.configure("Avis.Treeview", rowheight=25, fieldbackground="white",
                     background="white", borderwidth=0, font=("Segoe UI", 9))
        st.configure("Avis.Treeview.Heading", font=("Segoe UI", 8, "bold"),
                     background="#F0F0F2", foreground="#3A3A40",
                     relief="flat", padding=(6, 5))
        st.map("Avis.Treeview.Heading", background=[("active", "#E6E6EA")])
        st.map("Avis.Treeview", background=[("selected", "#FBE3E8")],
               foreground=[("selected", "#1A1A1A")])
        st.configure("Avis.Horizontal.TProgressbar", troughcolor="#EDEDF0",
                     background=AVIS_ROJO, borderwidth=0, thickness=6)

    def elegir(self):
        d = filedialog.askdirectory(title="Carpeta con los Excels de Rentway")
        if d:
            self.dir_var.set(d)

    # ---------- diálogo de configuración ----------
    def abrir_configuracion(self):
        """Credenciales y Telegram viven aquí, no en la pantalla principal:
        así no está el token a la vista de quien pase por delante."""
        d = tk.Toplevel(self.root)
        d.title("Configuración")
        d.configure(bg="white")
        d.resizable(False, False)
        d.transient(self.root)
        d.grab_set()
        try:
            d.iconbitmap(resource(os.path.join("assets", "avis.ico")))
        except Exception:
            pass

        tk.Frame(d, bg=AVIS_ROJO, height=4).pack(fill="x")

        def seccion(titulo, ayuda):
            tk.Label(d, text=titulo, bg="white", fg=AVIS_ROJO,
                     font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=18, pady=(16, 0))
            tk.Label(d, text=ayuda, bg="white", fg="#6A6A70", font=("Segoe UI", 8),
                     justify="left", wraplength=430).pack(anchor="w", padx=18, pady=(2, 8))
            m = tk.Frame(d, bg="white")
            m.pack(fill="x", padx=18)
            return m

        m1 = seccion("Acceso a Rentway",
                     "Necesario para que la vigilancia automática funcione sola: la sesión "
                     "del navegador caduca a los pocos días. Se guarda cifrado con Windows "
                     "y queda atado a este equipo y a este usuario.")
        tk.Label(m1, text="Usuario", bg="white", font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w")
        tk.Entry(m1, textvariable=self.user_var, width=26, relief="solid", bd=1,
                 font=("Segoe UI", 9)).grid(row=0, column=1, padx=8, ipady=3)
        tk.Label(m1, text="Contraseña", bg="white", font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=6)
        tk.Entry(m1, textvariable=self.pass_var, width=26, show="•", relief="solid", bd=1,
                 font=("Segoe UI", 9)).grid(row=1, column=1, padx=8, pady=6, ipady=3)
        ttk.Button(m1, text="Guardar", style="Avis.TButton",
                   command=self.guardar_credenciales).grid(row=1, column=2, padx=4)
        tk.Label(m1, textvariable=self.info_cred, bg="white", fg="#6A6A70",
                 font=("Segoe UI", 8)).grid(row=2, column=0, columnspan=3, sticky="w")

        m2 = seccion("Avisos por Telegram",
                     "Se avisa SOLO cuando hay cambios, no en cada pasada. El chat de un "
                     "grupo empieza por guion (por ejemplo -5140930532); no lo quites. "
                     "Al guardar se envía un mensaje de prueba.")
        tk.Label(m2, text="Token del bot", bg="white", font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w")
        tk.Entry(m2, textvariable=self.tg_token, width=26, show="•", relief="solid", bd=1,
                 font=("Segoe UI", 9)).grid(row=0, column=1, padx=8, ipady=3)
        tk.Label(m2, text="Chat", bg="white", font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=6)
        tk.Entry(m2, textvariable=self.tg_chat, width=26, relief="solid", bd=1,
                 font=("Segoe UI", 9)).grid(row=1, column=1, padx=8, pady=6, ipady=3)
        ttk.Button(m2, text="Guardar y probar", style="Avis.TButton",
                   command=self.guardar_telegram).grid(row=1, column=2, padx=4)
        tk.Label(m2, textvariable=self.info_tg, bg="white", fg="#6A6A70",
                 font=("Segoe UI", 8)).grid(row=2, column=0, columnspan=3, sticky="w")

        m3 = seccion("Avisos por correo",
                     "Se envían junto con los de Telegram, solo cuando hay cambios. "
                     "Gmail: smtp.gmail.com puerto 587 (con verificación en dos pasos "
                     "hace falta una «contraseña de aplicación»). Microsoft 365: "
                     "smtp.office365.com puerto 587.")
        etiquetas = [("Servidor", self.co_serv, 26, None), ("Puerto", self.co_puerto, 8, None),
                     ("Usuario", self.co_user, 26, None), ("Contraseña", self.co_pass, 26, "•"),
                     ("Enviar desde", self.co_remit, 34, None),
                     ("Destinatarios", self.co_dest, 34, None)]
        for i, (txt, var, ancho, oculto) in enumerate(etiquetas):
            tk.Label(m3, text=txt, bg="white", font=("Segoe UI", 9)).grid(row=i, column=0, sticky="w", pady=3)
            e = tk.Entry(m3, textvariable=var, width=ancho, relief="solid", bd=1,
                         font=("Segoe UI", 9))
            if oculto:
                e.configure(show=oculto)
            e.grid(row=i, column=1, padx=8, pady=3, ipady=3, sticky="w")
        tk.Label(m3, text="opcional: buzón compartido", bg="white", fg="#9A9AA0",
                 font=("Segoe UI", 8)).grid(row=4, column=2, sticky="w")
        tk.Label(m3, text="separa varios con comas", bg="white", fg="#9A9AA0",
                 font=("Segoe UI", 8)).grid(row=5, column=2, sticky="w")
        ttk.Button(m3, text="Guardar y probar", style="Avis.TButton",
                   command=self.guardar_correo).grid(row=1, column=2, rowspan=2, padx=4)
        tk.Label(m3, textvariable=self.info_co, bg="white", fg="#6A6A70",
                 font=("Segoe UI", 8)).grid(row=6, column=0, columnspan=3, sticky="w")

        m4 = seccion("Vigilancia automática", "")
        tk.Label(m4, text=self._texto_tarea(), bg="white", fg="#3A3A40",
                 font=("Segoe UI", 9), justify="left").pack(anchor="w")

        m5 = seccion("Versión y actualizaciones",
                     "El programa comprueba en cada pasada si hay una versión nueva "
                     "publicada y la deja descargada; se aplica sola al reiniciarlo.")
        fila = tk.Frame(m5, bg="white")
        fila.pack(fill="x")
        tk.Label(fila, text="Versión instalada: %s" % VERSION, bg="white",
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Button(fila, text="Buscar ahora",
                   command=self.buscar_actualizacion_gui).pack(side="left", padx=10)
        self.info_act = tk.StringVar(
            value=("Canal: %s" % url_actualizaciones()) if url_actualizaciones()
            else "Sin canal de actualizaciones configurado.")
        tk.Label(m5, textvariable=self.info_act, bg="white", fg="#6A6A70",
                 font=("Segoe UI", 8), wraplength=430, justify="left").pack(anchor="w", pady=(4, 0))

        pie = tk.Frame(d, bg="white")
        pie.pack(fill="x", pady=(18, 14), padx=18)
        ttk.Button(pie, text="Cerrar", command=d.destroy).pack(side="right")
        d.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - d.winfo_width()) // 2
        y = self.root.winfo_rooty() + 80
        d.geometry("+%d+%d" % (max(x, 0), max(y, 0)))

    @staticmethod
    def _texto_tarea():
        """Lee del Programador de tareas si la vigilancia está puesta."""
        try:
            import subprocess
            r = subprocess.run(
                ["schtasks", "/Query", "/TN", "AVIS - Monitor de Oneways (diario)", "/FO", "LIST"],
                capture_output=True, text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode != 0:
                return "No está programada en este equipo (solo se analiza a mano)."
            prox = ""
            for l in r.stdout.splitlines():
                if "xima" in l:           # 'Hora próxima ejecución'
                    prox = l.split(":", 1)[1].strip()
            return ("Programada cada 2 horas, se ejecuta sola y sin ventanas.\n"
                    "Próxima pasada: %s" % (prox or "—"))
        except Exception:
            return "No he podido consultar el Programador de tareas."

    # ---------- credenciales e instancia única ----------
    def _estado_credenciales(self):
        import credenciales
        u, _ = credenciales.cargar(app_dir())
        if u:
            self.user_var.set(u)
            self.info_cred.set("guardadas y cifradas (entra sola)")
        else:
            self.info_cred.set("sin guardar — hará falta entrar a mano")

    def guardar_credenciales(self):
        import credenciales
        u, c = self.user_var.get().strip(), self.pass_var.get()
        if not u or not c:
            messagebox.showwarning("Credenciales", "Pon usuario y contraseña.")
            return
        try:
            credenciales.guardar(app_dir(), u, c)
            self.pass_var.set("")
            self.info_cred.set("guardadas y cifradas (entra sola)")
            registrar("Credenciales guardadas (cifradas con DPAPI) para el usuario %s" % u)
            messagebox.showinfo(
                "Credenciales",
                "Guardadas y cifradas con DPAPI de Windows.\n\n"
                "El fichero queda atado a este equipo y a este usuario: si alguien "
                "se lo lleva a otro ordenador, no sirve de nada.")
        except Exception as e:
            messagebox.showerror("Credenciales", "No pude guardarlas: %s" % e)

    def guardar_telegram(self):
        import credenciales, avisos
        tok, chat = self.tg_token.get().strip(), self.tg_chat.get().strip()
        if not tok or not chat:
            messagebox.showwarning("Telegram", "Pon el token del bot y el chat.")
            return
        try:
            nombre = avisos.comprobar(tok)
        except Exception as e:
            messagebox.showerror("Telegram", "El token no vale: %s" % str(e)[:150])
            return
        if not avisos.enviar(tok, chat, "<b>AVIS · Monitor de Oneways</b>\n"
                                        "Avisos configurados correctamente en este equipo."):
            messagebox.showerror("Telegram",
                                 "El token es válido (%s) pero no pude escribir en ese chat.\n\n"
                                 "Si es un grupo, añade el bot al grupo y escribe algo primero." % nombre)
            return
        credenciales.guardar_telegram(app_dir(), tok, chat)
        self.tg_token.set("")
        self.info_tg.set("guardado (%s) — te acabo de mandar un mensaje" % nombre)
        registrar("Telegram configurado: bot %s, chat %s" % (nombre, chat))
        messagebox.showinfo("Telegram",
                            "Listo. Bot %s.\n\nTe he mandado un mensaje de prueba a ese chat.\n"
                            "El token se guarda cifrado, igual que la contraseña." % nombre)

    def _estado_telegram(self):
        import credenciales
        tok, chat = credenciales.cargar_telegram(app_dir())
        if tok and chat:
            self.tg_chat.set(chat)
            self.info_tg.set("configurado (avisa solo si hay cambios)")
        else:
            self.info_tg.set("sin configurar — no se enviarán avisos")

    def guardar_correo(self):
        import credenciales, correo
        serv, puerto = self.co_serv.get().strip(), self.co_puerto.get().strip()
        usu, cla = self.co_user.get().strip(), self.co_pass.get()
        dest = self.co_dest.get().strip()
        remit = self.co_remit.get().strip()
        if not serv or not puerto or not dest:
            messagebox.showwarning("Correo", "Faltan servidor, puerto o destinatarios.")
            return
        try:
            correo.comprobar(serv, puerto, usu, cla)
        except Exception as e:
            messagebox.showerror("Correo", "No pude conectar con el servidor:\n\n%s" % str(e)[:250])
            return
        if not correo.enviar(serv, puerto, usu, cla, dest,
                             "AVIS · Monitor de Oneways — prueba",
                             "<p>Configuración de correo correcta.</p>"
                             "<p>A partir de ahora recibirás aquí los cambios en los oneways.</p>",
                             remitente=remit or None, oculto=True):
            messagebox.showerror("Correo", "Conecté con el servidor pero no pude enviar.")
            return
        credenciales.guardar_correo(app_dir(), serv, puerto, usu, cla, dest, remit)
        self.co_pass.set("")
        self.info_co.set("configurado — te acabo de mandar un correo de prueba")
        registrar("Correo configurado: %s:%s (desde %s) -> %s"
                  % (serv, puerto, remit or usu, dest))
        messagebox.showinfo("Correo", "Listo. Te he enviado un correo de prueba.\n\n"
                                      "La contraseña se guarda cifrada.")

    def _estado_correo(self):
        import credenciales
        cfg = credenciales.cargar_correo(app_dir())
        if cfg:
            self.co_serv.set(cfg.get("servidor", ""))
            self.co_puerto.set(cfg.get("puerto", "587"))
            self.co_user.set(cfg.get("usuario", ""))
            self.co_remit.set(cfg.get("remitente", ""))
            self.co_dest.set(cfg.get("destinatarios", ""))
            self.info_co.set("configurado (avisa solo si hay cambios)")
        else:
            self.info_co.set("sin configurar — no se enviarán correos")

    def buscar_actualizacion_gui(self):
        if not url_actualizaciones():
            messagebox.showinfo(
                "Actualizaciones",
                "Todavía no hay canal configurado.\n\n"
                "Se configura poniendo un fichero 'actualizacion.txt' junto al programa "
                "con la dirección del manifiesto (version.json).")
            return
        try:
            m, nueva = buscar_actualizacion(descargar=True)
        except Exception as e:
            messagebox.showerror("Actualizaciones", str(e)[:250])
            return
        if not m:
            self.info_act.set("No pude consultar el canal de actualizaciones.")
            return
        if nueva:
            self.info_act.set("Descargada la versión %s. Se aplicará al reiniciar."
                              % m.get("version"))
            messagebox.showinfo(
                "Hay una versión nueva",
                "Versión %s disponible (tienes la %s).\n\n%s\n\n"
                "Ya está descargada: se instalará sola la próxima vez que abras el programa."
                % (m.get("version"), VERSION, m.get("notas", "")))
        else:
            self.info_act.set("Estás en la última versión (%s)." % VERSION)
            messagebox.showinfo("Actualizaciones", "Ya tienes la última versión (%s)." % VERSION)

    def _avisar_si_otra_instancia(self):
        """Si otro portátil ya está vigilando, avisar: dos a la vez duplican los
        avisos y cada uno compara contra su propio snapshot."""
        try:
            import instancia
            carpeta = instancia.carpeta_por_defecto(app_dir())
            otra = instancia.otra_instancia(carpeta)
            if otra:
                messagebox.showwarning(
                    "Ya hay otro equipo vigilando",
                    "El monitor ya está corriendo en:\n\n"
                    "    Equipo:  %s\n    IP:      %s\n    Usuario: %s\n"
                    "    Última señal: hace %s minutos\n\n"
                    "Debe vigilar UN SOLO equipo: si corren dos se duplican los avisos "
                    "y cada uno compara contra su propio histórico.\n\n"
                    "Puedes usar esta copia para consultar, pero no dejes la tarea "
                    "programada activa en los dos."
                    % (otra.get("equipo"), otra.get("ip"), otra.get("usuario"),
                       otra.get("edad_min")))
                registrar("AVISO: otra instancia activa en %s (%s)"
                          % (otra.get("equipo"), otra.get("ip")))
        except Exception:
            pass

    # ---------- descarga automática desde Rentway ----------
    def descargar(self):
        if self.worker and self.worker.is_alive():
            return
        carpeta = self.dir_var.get().strip()
        if not carpeta:
            messagebox.showerror("Sin carpeta", "Indica una carpeta de destino.")
            return
        try:
            dias = max(1, int(self.dias_var.get()))
        except ValueError:
            dias = 7
        self.btn_bajar.configure(state="disabled")
        self.estado.set("Trabajando…")
        self.marco_prog.pack(fill="x", before=self.txt.master.master)
        self.prog.configure(value=0)
        self.lbl_prog.configure(text="Abriendo Rentway…")
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("end", "Descargando de Rentway…\n")
        self.txt.configure(state="disabled")
        self.worker = threading.Thread(target=self._bajar,
                                       args=(carpeta, dias, self.ampliado_var.get()),
                                       daemon=True)
        self.worker.start()

    def _bajar(self, carpeta, dias, ampliado):
        def anota(m):
            registrar(m)
            self.cola.put(("log", str(m)))
        try:
            anota("=== Descarga solicitada (dias=%d, ampliado=%s, destino=%s) ==="
                  % (dias, ampliado, carpeta))
            import rentway_export, credenciales
            anota("modulo rentway_export cargado")
            u, c = credenciales.cargar(app_dir())
            rentway_export.descargar_informes(
                carpeta, dias=dias,
                # el navegador va INVISIBLE tambien aqui: no tiene que molestar
                # a quien este usando el portatil
                visible=False,
                esperar_login=0 if u else 300,
                log=anota, base_app=app_dir(), ampliado=ampliado,
                credenciales=(u, c) if u else None,
                progreso=lambda h, t, txt: self.cola.put(("prog", (h, t, txt))))
            anota("=== Descarga terminada con exito ===")
            self.cola.put(("ok", None))
        except Exception as e:
            import traceback
            registrar("ERROR: " + traceback.format_exc())
            self.cola.put(("error", str(e)))

    def _poll(self):
        try:
            while True:
                tipo, dato = self.cola.get_nowait()
                if tipo == "log":
                    self.txt.configure(state="normal")
                    self.txt.insert("end", dato + "\n")
                    self.txt.see("end")
                    self.txt.configure(state="disabled")
                elif tipo == "prog":
                    hecho, total, txt = dato
                    self.prog.configure(value=100.0 * hecho / max(1, total))
                    self.lbl_prog.configure(text="%s   (%d de %d informes)"
                                            % (txt, hecho, total))
                elif tipo == "ok":
                    self.btn_bajar.configure(state="normal")
                    self.prog.configure(value=100)
                    self.lbl_prog.configure(text="Informes descargados. Analizando…")
                    self.estado.set("Analizando…")
                    self.analizar()
                    self.marco_prog.pack_forget()
                elif tipo == "error":
                    self.btn_bajar.configure(state="normal")
                    self.marco_prog.pack_forget()
                    self.estado.set("Error en la descarga.")
                    messagebox.showerror("Rentway", "No pude descargar los informes:\n\n" + dato)
        except queue.Empty:
            pass
        self.root.after(300, self._poll)

    def analizar(self):
        carpeta = self.dir_var.get().strip()
        fich = encontrar_excels(carpeta)
        res, abi = fich.get("reservas"), fich.get("abiertos")
        if not res and not abi:
            messagebox.showerror("Sin Excels", "No encuentro 'reservations_list_*.xlsx' ni 'open_*.xlsx' en esa carpeta.")
            return
        try:
            ow = leer_oneways(res, abi)
            enriquecer(ow, fich)
            completar_grupos(ow)
            anulados = leer_anulados(fich.get("anulados"))
        except Exception as e:
            messagebox.showerror("Error", "No pude leer los Excels: " + str(e))
            return
        ayer, fecha_ayer = cargar_snapshot_anterior()
        # mismo cuidado que en el modo desatendido: {} es falso pero SI es
        # una referencia valida (una pasada sin oneways)
        cambios = comparar(ow, ayer, anulados) if ayer is not None else []
        guardar_snapshot(ow)

        # tabla oneways activos
        self.tv.delete(*self.tv.get_children())
        activos = [r for r in ow.values() if r["activo"]]
        for i, r in enumerate(sorted(activos, key=lambda x: x["fecha_salida"])):
            tel = r.get("telefono") or r.get("telefono_conductor") or ""
            self.tv.insert("", "end", tags=("par",) if i % 2 else (),
                           values=(r["tipo"], r["num"], r.get("grupo") or "—",
                                   (r["matricula"] if r.get("contrato") else "") or "—",
                                   f"{r['salida']} → {r['devolucion']}", r["fecha_salida"],
                                   r["fecha_llegada"], r["estado"], r["cliente"],
                                   r.get("vuelo") or "—", tel or "—"))
        self.lbl_cuenta.configure(
            text="%d en los próximos %s días" % (len(activos), self.dias_var.get()))

        # cambios
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        if not ayer:
            self.txt.insert("end", "Primer análisis: guardado como referencia. Mañana ya podré comparar.\n")
        elif not cambios:
            self.txt.insert("end", f"Sin cambios respecto a {fecha_ayer}.\n")
        else:
            self.txt.insert("end", f"Comparando con {fecha_ayer} — {len(cambios)} cambio(s):\n\n")
            for c in cambios:
                r = c["reg"]
                base = f"{r['tipo']} {r['num']} (grupo {r.get('grupo') or '?'}, {r['salida']}→{r['devolucion']})"
                if c["tipo"] == "NUEVO":
                    self.txt.insert("end", f"● NUEVO ONEWAY: {base} salida {r['fecha_salida']} | {r['estado']}\n", "NUEVO")
                    detalle = self._detalle(r)
                    if detalle:
                        self.txt.insert("end", "     " + detalle + "\n")
                elif c["tipo"] == "ANULADO":
                    self.txt.insert("end", f"● ONEWAY ANULADO: {base} | {r['estado']}\n", "DESAP")
                elif c["tipo"] == "DESAPARECIDO":
                    if c.get("motivo") == "ANULADO":
                        self.txt.insert("end", f"● ONEWAY ANULADO: {base}\n", "DESAP")
                    else:
                        self.txt.insert("end", f"● YA NO ONEWAY: {base} (terminado o fuera de rango)\n", "DESAP")
                else:
                    for campo, viejo, nuevo in c["difs"]:
                        self.txt.insert("end", f"● CAMBIO {base}: {campo}  '{viejo}' → '{nuevo}'\n", "CAMBIO")
        self.txt.configure(state="disabled")

        avisar_telegram(cambios, activos, fecha_ayer)
        avisar_correo(cambios, activos, fecha_ayer)

        ampl = [k for k in ("detalle", "anulados", "contacto_res", "contacto_con") if fich.get(k)]
        self.estado.set("%d oneway(s) · %d cambio(s) · datos ampliados %d/4 · comparado con %s"
                        % (len(activos), len(cambios), len(ampl), fecha_ayer or "nada previo"))
        self.lbl_avisos.configure(text=self.info_tg.get())

    @staticmethod
    def _detalle(r):
        """Línea de contexto ampliado para un oneway (solo lo que tenga valor)."""
        partes = []
        for etiqueta, clave in (("vuelo", "vuelo"), ("entrega en", "lugar_entrega"),
                                ("franquicia", "franquicia"), ("extras", "extras"),
                                ("tel.", "telefono"), ("email", "email")):
            v = (r.get(clave) or "").strip()
            if v:
                partes.append(f"{etiqueta} {v}")
        obs = (r.get("observaciones") or "").strip()
        if obs:
            partes.append("obs: " + obs[:70])
        return " · ".join(partes)


def url_actualizaciones(base=None):
    """De dónde se leen las actualizaciones.

    Se cambia SIN recompilar: basta con un fichero 'actualizacion.txt' al lado
    del programa. Valores admitidos:
      - una URL https://…/version.json   (GitHub Releases, servidor propio…)
      - la palabra 'onedrive'            -> usa la carpeta compartida de OneDrive
                                            de CADA equipo, que es distinta en
                                            cada usuario y por eso se resuelve
                                            aquí y no se escribe a mano.
    """
    base = base or app_dir()
    u = URL_ACTUALIZACIONES
    f = os.path.join(base, "actualizacion.txt")
    if os.path.exists(f):
        try:
            # utf-8-sig: el Bloc de notas y 'Set-Content -Encoding UTF8' escriben
            # un BOM invisible al principio que se colaba dentro de la URL
            with open(f, encoding="utf-8-sig") as h:
                v = h.read().strip().lstrip("﻿").strip()
            if v:
                u = v
        except Exception:
            pass
    if not u:
        return ""
    if u.lower().startswith(("http://", "https://", "file:")):
        return u
    # cualquier otra cosa se trata como una RUTA (unidad de red, UNC o local)
    p = u if u.lower().endswith(".json") else os.path.join(u, "version.json")
    return "file:///" + os.path.abspath(p).replace("\\", "/")


_MAPA_ISLAS = None


def mapa_islas():
    """{codigo_oficina: isla}. Lo genera herramientas/mapa_islas.py del catalogo
    de Rentway; aqui solo se lee. Si falta el fichero se devuelve {} y todo el
    reparto se cae al lado seguro: todos reciben todo."""
    global _MAPA_ISLAS
    if _MAPA_ISLAS is None:
        try:
            with open(resource("oficinas_islas.json"), encoding="utf-8") as f:
                _MAPA_ISLAS = json.load(f)
        except Exception as e:
            registrar("No pude leer el mapa de islas (%s). Todos recibiran todo."
                      % str(e)[:90])
            _MAPA_ISLAS = {}
    return _MAPA_ISLAS


def _lista(v):
    if isinstance(v, (list, tuple, set)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [d.strip() for d in str(v or "").replace(";", ",").split(",") if d.strip()]


def islas_de(reg, mapa):
    """Islas que toca un oneway y si alguna oficina es desconocida.

    Son SIEMPRE dos oficinas, la que suelta el coche y la que lo recibe, y las
    dos tienen que enterarse. Pueden caer en la misma isla --un TFN->TFS es
    Tenerife y Tenerife-- porque oneway significa oficina distinta, no isla
    distinta.
    """
    islas, desconocida = set(), False
    for campo in ("salida", "devolucion"):
        cod = str(reg.get(campo) or "").strip()
        isla = mapa.get(cod)
        if isla:
            islas.add(isla)
        else:
            desconocida = True
    return islas, desconocida


def repartir(cambios, siempre, por_isla, mapa):
    """Agrupa los avisos por DESTINATARIO, no por isla.

    Si se mandara un correo por isla, quien cubre dos --moalvarez@ esta en
    Fuerteventura y en Lanzarote-- recibiria dos veces el mismo aviso de un
    oneway que va de una a otra. Asi cada persona sale una sola vez, con
    exactamente los oneways que le tocan.

    Devuelve [(destinatarios, cambios)] y la lista de oficinas sin isla.

    REGLA DE ORO: lo que no se sabe se manda a TODO EL MUNDO, nunca a nadie. Una
    oficina nueva o una isla sin lista tiene que producir un correo de mas, no un
    silencio -- un silencio no se nota hasta que alguien pregunta por un coche.
    """
    todas = set(siempre)
    for v in por_isla.values():
        todas |= set(_lista(v))

    para_quien, huerfanas = {}, set()
    for i, c in enumerate(cambios):
        islas, desconocida = islas_de(c["reg"], mapa)
        destino = set(siempre)
        if desconocida:
            destino |= todas
            for campo in ("salida", "devolucion"):
                cod = str(c["reg"].get(campo) or "").strip()
                if cod and cod not in mapa:
                    huerfanas.add(cod)
        for isla in islas:
            gente = _lista(por_isla.get(isla))
            if gente:
                destino |= set(gente)
            else:
                # isla conocida pero sin nadie asignado (El Hierro, La Gomera)
                destino |= todas
                huerfanas.add(isla)
        for d in destino:
            para_quien.setdefault(d, set()).add(i)

    lotes = {}
    for correo_dest, indices in para_quien.items():
        lotes.setdefault(frozenset(indices), []).append(correo_dest)
    return ([(sorted(gente), [cambios[i] for i in sorted(idx)])
             for idx, gente in lotes.items()], sorted(huerfanas))


def _asunto_cambios(cambios):
    """Resume los cambios en una linea. El asunto es lo unico que mucha gente
    va a leer, asi que dice QUE ha pasado y no solo que ha pasado algo."""
    n = len([c for c in cambios if c.get("tipo") == "NUEVO"])
    a = len([c for c in cambios if c.get("tipo") == "ANULADO"
             or (c.get("tipo") == "DESAPARECIDO" and c.get("motivo") == "ANULADO")])
    f = len([c for c in cambios if c.get("tipo") == "DESAPARECIDO"
             and c.get("motivo") != "ANULADO"])
    m = len([c for c in cambios if c.get("tipo") == "CAMBIO"])
    e = len([c for c in cambios if c.get("tipo") == "EN_CURSO"])
    partes = []
    if n:
        partes.append("%d oneway%s NUEVO%s" % (n, "s" if n > 1 else "", "S" if n > 1 else ""))
    if a:
        partes.append("%d anulado%s" % (a, "s" if a > 1 else ""))
    if f:
        partes.append("%d baja%s" % (f, "s" if f > 1 else ""))
    if e:
        partes.append("%d recogido%s" % (e, "s" if e > 1 else ""))
    if m:
        partes.append("%d cambio%s" % (m, "s" if m > 1 else ""))
    return "AVIS · " + (", ".join(partes) if partes else "sin novedades")


def avisar_correo(cambios, activos, referencia, base=None):
    """Envía el aviso por correo, con EL MISMO CONTENIDO QUE TELEGRAM.

    Antes solo mandaba los oneways NUEVOS, porque son los que obligan a mover
    un coche. Cambiado el 24/08/2026 a peticion del usuario: los avisos tienen
    que ir sincronizados. Motivo practico: la lista paso de 2 a 27 personas de
    las cuatro islas, y la mayoria NO esta en el grupo de Telegram; con el
    filtro anterior se habrian perdido las anulaciones y los cambios de
    matricula o de hora, que tambien cambian el trabajo del dia.

    `correo.cuerpo_cambios` ya sabia pintar los tres tipos: el filtro estaba
    solo aqui.
    """
    try:
        import credenciales, correo
        base = base or app_dir()
        cfg = credenciales.cargar_correo(base)
        if not cfg or not cambios:
            return False

        siempre = _lista(cfg.get("destinatarios"))
        por_isla = cfg.get("por_isla") or {}
        if por_isla:
            lotes, huerfanas = repartir(cambios, siempre, por_isla, mapa_islas())
        else:
            # Sin reparto configurado se comporta como toda la vida. Es el
            # camino por defecto a proposito: quien no haya configurado islas no
            # debe descubrirlo porque un dia dejaron de llegarle avisos.
            lotes, huerfanas = [(siempre, cambios)], []

        alguno = False
        for gente, trozo in lotes:
            if not gente or not trozo:
                continue
            ok = correo.enviar(cfg["servidor"], cfg["puerto"], cfg["usuario"], cfg["clave"],
                               gente, _asunto_cambios(trozo),
                               correo.cuerpo_cambios(trozo, activos, referencia),
                               remitente=cfg.get("remitente") or None,
                               log=registrar, oculto=True)
            alguno = alguno or ok
            registrar("Aviso por correo %s (%d cambio(s), %d destinatario(s))"
                      % ("enviado" if ok else "NO enviado", len(trozo), len(gente)))

        if huerfanas:
            # No es un detalle: significa que alguien ha recibido un correo que
            # quiza no le tocaba, o --peor-- que hay una oficina cuya isla no
            # sabemos. Se avisa para poder arreglar el mapa, no para tapar nada.
            avisar_fallo("Sin isla asignada: %s. Esos oneways se han mandado a "
                         "TODO EL MUNDO para no dejar a nadie sin avisar. Revisa "
                         "el mapa de oficinas o la lista de destinatarios."
                         % ", ".join(huerfanas[:12]), base)
        return alguno
    except Exception as e:
        registrar("Fallo al avisar por correo: %s" % str(e)[:120])
        return False


def probar_correo(destino=None, base=None):
    """Manda un correo de prueba y cuenta lo que pasa. Devuelve True/False.

    En Windows esto lo hacia el boton "Guardar y probar" de la ventana. En el
    servidor no hay ventana, y comprobar la lista de destinatarios a base de
    esperar a que aparezca un oneway nuevo no es forma de trabajar: pueden
    pasar dias. Con `--probar-correo` se verifica en veinte segundos.

    Sin argumento manda a TODA la lista configurada. Con una direccion detras,
    solo a esa: sirve para probar sin molestar a los demas.
    """
    import credenciales, correo
    base = base or app_dir()
    cfg = credenciales.cargar_correo(base)
    if not cfg:
        registrar("PRUEBA DE CORREO: no hay configuracion de correo guardada.")
        return False
    para = destino or cfg["destinatarios"]
    lista = [d.strip() for d in str(para).replace(";", ",").split(",") if d.strip()]
    registrar("PRUEBA DE CORREO -> %s (via %s:%s como %s)"
              % (", ".join(lista), cfg["servidor"], cfg["puerto"], cfg["usuario"]))
    cuerpo = (
        "<div style=\"font-family:Segoe UI,Arial,sans-serif\">"
        "<h2 style=\"color:#D4002B;margin:0 0 4px\">AVIS &middot; Monitor de Oneways</h2>"
        "<p>Esto es un <b>correo de prueba</b>. Si lo estas leyendo, esta "
        "direccion queda dada de alta en los avisos de <b>oneways</b>.</p>"
        "<p style=\"color:#444\">Un <b>oneway</b> es una reserva o contrato que se "
        "<b>entrega en una oficina y se devuelve en otra</b>. Recibiras un aviso "
        "cuando aparezca uno nuevo, cuando se anule y cuando cambie algo suyo "
        "(matricula, fechas o estado). <b>Solo se escribe si hay novedades</b>: "
        "si no llega nada, es que no hay cambios.</p>"
        "<p style=\"color:#666;font-size:13px\">Enviado desde el servidor de "
        "vigilancia el " + datetime.datetime.now().strftime("%d/%m/%Y a las %H:%M") +
        ". No hay que responder.</p></div>")
    ok = correo.enviar(cfg["servidor"], cfg["puerto"], cfg["usuario"], cfg["clave"],
                       lista, "AVIS · Monitor de Oneways — correo de prueba",
                       cuerpo, remitente=cfg.get("remitente") or None, log=registrar,
                       oculto=True)
    registrar("PRUEBA DE CORREO: %s" % ("ENVIADO" if ok else "FALLO"))
    return ok


def avisar_telegram(cambios, activos, referencia, base=None):
    """Manda el aviso SOLO si hay cambios. Un fallo aquí nunca tumba la pasada."""
    try:
        import credenciales, avisos
        base = base or app_dir()
        token, chat = credenciales.cargar_telegram(base)
        if not token or not chat:
            return False
        if not cambios:
            registrar("Sin cambios: no se envía aviso de Telegram.")
            return False
        ok = avisos.enviar(token, chat, avisos.texto_cambios(cambios, activos, referencia),
                           log=registrar)
        registrar("Aviso de Telegram %s (%d cambio(s))"
                  % ("enviado" if ok else "NO enviado", len(cambios)))
        return ok
    except Exception as e:
        registrar("Fallo al avisar por Telegram: %s" % str(e)[:120])
        return False


# ==================== LA PASADA (tarea programada y /revisar) ====================
def ejecutar_pasada(dias=7, ampliado=True, quien="tarea", avisar=True):
    """Descarga, analiza, compara y avisa. Sin ventana.

    Lo comparten la Tarea Programada y el comando /revisar de Telegram, para que
    los dos hagan EXACTAMENTE lo mismo.

    `avisar=False` (--sin-avisos) hace la pasada entera y guarda la foto, pero
    no manda nada a nadie: solo escribe en el log lo que HABRIA avisado. Es para
    desplegar un cambio que amplia lo que se ve (el 17/09/2026, 13 oneways en
    carretera que antes no se veian) sin que las oficinas reciban de golpe
    "nuevos" que no lo son. Devuelve un dict con el resultado:
      {"estado": "ok", "cambios": [...], "activos": [...], "referencia": "..."}
      {"estado": "error", "error": "..."}
      {"estado": "otro_equipo"|"ocupado", "otra": {...}}
    """
    import instancia, credenciales
    base = app_dir()
    carpeta_señal = instancia.carpeta_por_defecto(base)
    registrar("=== PASADA [%s] (dias=%d, ampliado=%s%s) ==="
              % (quien, dias, ampliado, "" if avisar else ", SIN AVISOS"))
    registrar("Señal de instancia en: %s" % carpeta_señal)

    otra = instancia.otra_instancia(carpeta_señal)
    if otra:
        registrar("NO EJECUTO: ya hay otro equipo vigilando -> %s (IP %s, usuario %s, "
                  "señal de hace %s min). Se evita duplicar avisos."
                  % (otra.get("equipo"), otra.get("ip"), otra.get("usuario"),
                     otra.get("edad_min")))
        return {"estado": "otro_equipo", "otra": otra}

    # La tarea programada y la escucha son procesos DISTINTOS del mismo equipo,
    # asi que el control de arriba no los ve como rivales. Sin este candado los
    # dos abririan Chromium sobre el mismo perfil y se corrompe.
    bloqueo = instancia.BloqueoLocal(base, quien)
    bloqueo.__enter__()
    if not bloqueo.tomado:
        o = bloqueo.ocupado_por or {}
        registrar("NO EJECUTO: ya hay una pasada en curso en este equipo "
                  "(%s, desde hace %s min)." % (o.get("quien"), o.get("edad_min")))
        return {"estado": "ocupado", "otra": o}

    latido = instancia.Latido(carpeta_señal)
    latido.start()
    despierto = MantenerDespierto()
    despierto.__enter__()
    try:
        asegurar_sin_suspension(base)
        esperar_red()
        usuario, clave = credenciales.cargar(base)
        if not usuario:
            registrar("AVISO: no hay credenciales guardadas. Si la sesion ha caducado "
                      "esto fallara: abre el programa y guarda usuario y contraseña.")
        carpeta = os.path.join(os.path.expanduser("~"), "Downloads")
        import rentway_export
        bajados = rentway_export.descargar_informes(
            carpeta, dias=dias, visible=False, esperar_login=0,
            log=registrar, base_app=base, ampliado=ampliado,
            credenciales=(usuario, clave) if usuario else None)

        ayer, fecha_ayer = cargar_snapshot_anterior()

        # OJO: se usa SOLO lo que se ha bajado EN ESTA PASADA (`bajados`), no lo
        # que haya en Downloads. encontrar_excels() coge el fichero mas reciente
        # que encuentre, asi que cuando un informe falla devuelve el de una
        # pasada anterior sin decir nada. Hasta el 17/09/2026 esto se cuidaba
        # solo con Abiertos; los ampliados seguian leyendose de Downloads.
        fich = {k: (bajados or {}).get(k) for k in PATRONES_EXCEL}

        problemas = comprobar_formato(fich)
        if problemas:
            registrar("FORMATO DE INFORME CAMBIADO: " + " | ".join(problemas))
            avisar_fallo("Rentway ha cambiado el formato de algun informe y puede "
                         "que se esten perdiendo oneways sin decir nada. "
                         + " | ".join(problemas), base)

        abiertos_hoy = fich.get("abiertos")
        no_oneway = set()
        ow = leer_oneways(fich.get("reservas"), abiertos_hoy, no_oneway)
        if not abiertos_hoy:
            # Faltar este informe es un ERROR, no una linea de log: el
            # 25 y el 26/08/2026 se colgo en cinco pasadas seguidas (00:00 a
            # 07:00) y de madrugada el log no lo lee nadie.
            arrastrar_contratos(ow, ayer, registrar)
            avisar_fallo(
                "No se pudo descargar el informe de Abiertos (contratos) tras dos "
                "intentos. Conservo lo ultimo conocido de los contratos; los "
                "oneways de reserva se vigilan con normalidad.",
                base)
        enriquecer(ow, fich)
        conservar_conocidos(ow, ayer)
        completar_grupos(ow)
        anulados = leer_anulados(fich.get("anulados"))
        # OJO: 'if ayer' era un BUG. Un snapshot sin oneways es {} y en Python
        # eso es falso, asi que se saltaba la comparacion y el PRIMER oneway
        # tras un periodo sin ninguno no se avisaba nunca.
        silenciosos = []
        cambios = (comparar(ow, ayer, anulados, no_oneway, log=registrar,
                            silenciosos=silenciosos)
                   if ayer is not None else [])
        guardar_snapshot(ow)

        activos = [r for r in ow.values() if r["activo"]]
        registrar("Oneways: %d (activos: %d) · Cambios vs %s: %d"
                  % (len(ow), len(activos), fecha_ayer or "(sin referencia)", len(cambios)))
        if avisar:
            avisar_telegram(cambios, activos, fecha_ayer, base)
            avisar_correo(cambios, activos, fecha_ayer, base)
            parte_diario(activos, base)
        elif cambios:
            registrar("SIN AVISOS: no se envia nada de lo siguiente.")
        # La hoja de Google va DESPUES de los avisos y nunca los retrasa ni los
        # tumba: es una vista. Aqui solo se deja el fichero; la hoja viene a
        # buscarlo (ver hoja.py). Si deja de actualizarse, lo delata su propio
        # "Actualizado: ..." de arriba.
        import hoja
        hoja.publicar(ow, cambios, silenciosos, mapa_islas(), base,
                      avisado=avisar, log=registrar)
        for c in cambios:
            r = c["reg"]
            base_txt = "%s %s (grupo %s, %s, %s→%s)" % (
                r["tipo"], r["num"], r.get("grupo") or "?",
                r["matricula"] or "s/m", r["salida"], r["devolucion"])
            if c["tipo"] == "NUEVO":
                registrar("  NUEVO ONEWAY: %s salida %s | %s" % (base_txt, r["fecha_salida"], r["estado"]))
            elif c["tipo"] == "ANULADO":
                registrar("  ONEWAY ANULADO: %s | %s" % (base_txt, r["estado"]))
            elif c["tipo"] == "DESAPARECIDO":
                registrar("  %s: %s" % ("ONEWAY ANULADO" if c.get("motivo") == "ANULADO"
                                        else "YA NO ONEWAY", base_txt))
            elif c["tipo"] == "EN_CURSO":
                registrar("  ONEWAY EN CURSO (coche recogido): %s contrato %s"
                          % (base_txt, r.get("contrato") or "?"))
            else:
                for campo, viejo, nuevo in c["difs"]:
                    registrar("  CAMBIO %s: %s '%s' → '%s'" % (base_txt, campo, viejo, nuevo))
        # cada pasada mira si hay version nueva y la deja descargada; se aplica
        # sola en el siguiente arranque
        try:
            buscar_actualizacion(descargar=True)
        except Exception:
            pass
        # La tarea programada hace de guardian de la escucha: si se ha caido,
        # la levanta. Es lo unico que corre con seguridad cada 2 horas.
        try:
            asegurar_escucha(base)
        except Exception:
            pass
        registrar("=== PASADA TERMINADA ===")
        return {"estado": "ok", "cambios": cambios, "activos": activos,
                "referencia": fecha_ayer}
    except Exception as e:
        import traceback
        registrar("ERROR EN LA PASADA: " + traceback.format_exc()[:1500])
        # Avisar de que ha fallado: el silencio no puede significar dos cosas
        # distintas ("todo bien" y "llevo dias roto").
        msg = "%s: %s" % (type(e).__name__, str(e).split("\n")[0][:200])
        avisar_fallo(msg, base)
        return {"estado": "error", "error": msg}
    finally:
        despierto.__exit__()
        latido.detener()
        bloqueo.__exit__()


def modo_desatendido(dias=7, ampliado=True, avisar=True):
    """Lo que ejecuta la Tarea Programada. Devuelve 0 si todo fue bien, 1 si
    hubo error y 2 si NO se ejecuto (otro equipo vigilando o pasada en curso)."""
    r = ejecutar_pasada(dias, ampliado, "tarea", avisar=avisar)
    return {"ok": 0, "error": 1, "otro_equipo": 2, "ocupado": 2}[r["estado"]]


class MantenerDespierto:
    """Impide que Windows duerma el equipo o MATE el proceso durante la pasada.

    POR QUE HACE FALTA: con Modern Standby (S0), la tarea programada despierta
    el portatil, pero como no hay actividad de usuario Windows lo vuelve a
    suspender enseguida. El proceso se congela a media pasada y las descargas
    mueren por tiempo de espera.

    POR QUE NO BASTA CON SetThreadExecutionState (auditoria del 10/08/2026):
    Microsoft documenta que en equipos con Modern Standby esa llamada se IGNORA.
    Ahi hay que usar POWER REQUESTS, y en concreto `PowerRequestExecutionRequired`,
    que es la unica que impide que el sistema SUSPENDA O TERMINE el proceso
    durante el standby.
    Sintoma que lo delato: las pasadas del 09 y 10/08 morian con codigo
    0xE0000027 justo despues de enviar los avisos, SIN dejar evento de error en
    Windows y SIN ejecutar el `finally` (el candado se quedaba sin borrar). Eso
    no es un fallo del programa: es una terminacion desde fuera.

    Se piden las dos cosas: la moderna (power request) y la antigua
    (SetThreadExecutionState) como red de seguridad en equipos sin S0.
    """
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_AWAYMODE_REQUIRED = 0x00000040

    # POWER_REQUEST_TYPE
    SISTEMA_REQUERIDO = 1        # PowerRequestSystemRequired: no suspender
    EJECUCION_REQUERIDA = 3      # PowerRequestExecutionRequired: no matarme

    def __init__(self):
        self._h = None
        self._puestas = []

    def __enter__(self):
        import ctypes
        # En un servidor no hay nada que mantener despierto: no se suspende
        # nunca. Todo esto existe solo por Modern Standby en portatiles.
        if not ES_WINDOWS:
            return self
        # 1) la antigua, por si el equipo no tiene Modern Standby
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(
                self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED | self.ES_AWAYMODE_REQUIRED)
        except Exception as e:
            registrar("SetThreadExecutionState fallo: %s" % str(e)[:80])

        # 2) la que de verdad cuenta en Modern Standby
        try:
            class _Razon(ctypes.Structure):
                _fields_ = [("Version", ctypes.c_ulong),
                            ("Flags", ctypes.c_ulong),
                            ("SimpleReasonString", ctypes.c_wchar_p)]

            k = ctypes.windll.kernel32
            k.PowerCreateRequest.restype = ctypes.c_void_p
            razon = _Razon(0, 0x1, "AVIS Monitor de Oneways: revision en curso")
            h = k.PowerCreateRequest(ctypes.byref(razon))
            if not h:
                raise OSError("PowerCreateRequest devolvio nulo")
            self._h = ctypes.c_void_p(h)
            for tipo in (self.SISTEMA_REQUERIDO, self.EJECUCION_REQUERIDA):
                if k.PowerSetRequest(self._h, tipo):
                    self._puestas.append(tipo)
            registrar("Equipo mantenido despierto (power requests: %s)."
                      % (", ".join(str(t) for t in self._puestas) or "ninguna"))
        except Exception as e:
            registrar("No pude crear la power request: %s" % str(e)[:90])
        return self

    def __exit__(self, *a):
        import ctypes
        # OJO: esto se llama desde el `finally` de ejecutar_pasada. En Linux
        # `ctypes.windll` no existe y la linea de abajo, que esta FUERA del
        # try, tumbaba el final de TODAS las pasadas, incluidas las que habian
        # ido bien.
        if not ES_WINDOWS:
            return False
        k = ctypes.windll.kernel32
        try:
            for tipo in self._puestas:
                k.PowerClearRequest(self._h, tipo)
            if self._h:
                k.CloseHandle(self._h)
        except Exception:
            pass
        try:
            k.SetThreadExecutionState(self.ES_CONTINUOUS)
        except Exception:
            pass
        return False


def _minutos_suspension_ca():
    """Minutos de inactividad tras los que el equipo se suspende ENCHUFADO.
    None si no se puede averiguar. 0 = nunca.

    OJO: `powercfg /query` informa en SEGUNDOS pero `powercfg /change` espera
    MINUTOS. Aquí se devuelve en minutos para poder comparar y escribir con la
    misma unidad.
    """
    import subprocess
    if not ES_WINDOWS:
        return 0                      # un servidor nunca se suspende
    try:
        s = subprocess.run(["powercfg", "/query", "SCHEME_CURRENT", "SUB_SLEEP", "STANDBYIDLE"],
                           capture_output=True, text=True, encoding="cp850",
                           errors="replace", timeout=20,
                           creationflags=0x08000000).stdout   # CREATE_NO_WINDOW
        # Los valores salen en este orden: minimo, maximo, incremento, CA, CC.
        # Se leen por posicion y no por el texto, que cambia con el idioma.
        hexes = re.findall(r"0x[0-9a-fA-F]{8}", s)
        if len(hexes) < 2:
            return None
        return int(hexes[-2], 16) // 60
    except Exception:
        return None


def asegurar_sin_suspension(base=None):
    """En un EQUIPO DEDICADO, vuelve a quitar la suspensión si alguien la repuso.

    POR QUE: el portátil es corporativo y está gestionado con Puppet. Si una
    directiva reaplica la política de energía, el equipo empieza a dormirse otra
    vez y las pasadas se pierden EN SILENCIO — que es exactamente lo que pasó el
    fin de semana del 8-10/08/2026 (9 pasadas de 32). No hace falta saber si
    Puppet lo toca o no: se comprueba cada pasada y, si está mal, se corrige.

    Solo actúa si existe el fichero `equipo_dedicado.txt` junto al programa, que
    crea el instalador cuando se responde que SÍ es un equipo dedicado. En el
    portátil de una persona NO se toca nunca la energía.
    """
    import subprocess
    base = base or app_dir()
    if not os.path.exists(os.path.join(base, "equipo_dedicado.txt")):
        return None
    actual = _minutos_suspension_ca()
    if actual is None or actual == 0:
        return actual
    registrar("AVISO: la suspensión con enchufe estaba en %d min; la quito otra vez "
              "(algo la ha repuesto: ¿directiva de empresa?)." % actual)
    try:
        for clave in ("standby-timeout-ac", "hibernate-timeout-ac"):
            subprocess.run(["powercfg", "/change", clave, "0"], capture_output=True,
                           timeout=20, creationflags=0x08000000)
        nuevo = _minutos_suspension_ca()
        if nuevo == 0:
            registrar("  corregido: ya no se suspende con enchufe.")
        else:
            registrar("  NO pude corregirlo (sigue en %s). Puede que lo fuerce una "
                      "directiva; habría que pedírselo a IT." % nuevo)
            avisar_fallo("El equipo se sigue suspendiendo a los %s min pese a "
                         "corregirlo. Se perderán revisiones." % nuevo, base)
    except Exception as e:
        registrar("  fallo al corregir la energía: %s" % str(e)[:90])
    return actual


LATIDO_ESCUCHA = "escucha_viva.txt"


def _latir_escucha(base, cada_seg=60):
    """La escucha deja constancia de que sigue viva."""
    while True:
        try:
            with open(os.path.join(base, LATIDO_ESCUCHA), "w", encoding="utf-8") as f:
                f.write(datetime.datetime.now().isoformat(timespec="seconds"))
        except Exception:
            pass
        time.sleep(cada_seg)


def asegurar_escucha(base=None):
    """Si la escucha se ha muerto, la vuelve a arrancar.

    POR QUE: la escucha es la que atiende /revisar y —en un equipo dedicado— la
    que mantiene la maquina despierta. Si se cae, no hay nadie que la levante
    hasta el siguiente inicio de sesion, que en un equipo desatendido puede no
    llegar en semanas. Como la tarea programada SI corre cada 2 h, se aprovecha
    para vigilarla: es el guardian natural.
    """
    base = base or app_dir()
    # En el servidor la escucha es un servicio de systemd con Restart=always:
    # levantarla desde aqui seria una segunda mano peleandose con la primera.
    if not ES_WINDOWS:
        return True
    marca = os.path.join(base, LATIDO_ESCUCHA)
    try:
        edad = (datetime.datetime.now() - datetime.datetime.fromisoformat(
            open(marca, encoding="utf-8").read().strip())).total_seconds() / 60.0
        if edad <= 5:
            return True                      # viva y coleando
        registrar("La escucha lleva %.0f min sin dar señales: la rearranco." % edad)
    except Exception:
        registrar("No hay señal de la escucha: la arranco.")

    exe = sys.executable if getattr(sys, "frozen", False) else None
    if not exe:
        return False                         # en modo desarrollo no se relanza
    try:
        import subprocess
        # DEVNULL + banderas: sin esto, en una app --windowed el hijo muere con
        # el padre y no sirve de nada relanzarla.
        subprocess.Popen([exe, "--escucha"], cwd=base,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         creationflags=0x00000008 | 0x08000000)  # DETACHED|NO_WINDOW
        registrar("  escucha relanzada.")
        return True
    except Exception as e:
        registrar("  no pude relanzar la escucha: %s" % str(e)[:90])
        return False


def _vigilar_energia(base, cada_seg=1800):
    """Cada media hora revisa que nadie haya repuesto la suspensión.

    La power request de la escucha ya impide que el equipo se duerma, pero esto
    es el segundo cinturón: si una directiva reaplica la política, se corrige
    sin esperar a la siguiente pasada. Y si no se puede corregir, avisa.
    """
    while True:
        try:
            asegurar_sin_suspension(base)
        except Exception:
            pass
        time.sleep(cada_seg)


def esperar_red(intentos=12, espera=10, log=None):
    """Tras despertar, la Wi-Fi tarda en volver (Modern Standby corta la red).
    Se espera a que Rentway responda antes de empezar."""
    import urllib.request
    log = log or registrar
    for i in range(intentos):
        try:
            urllib.request.urlopen("https://aviscanarias.jimpisoft.pt/login", timeout=10)
            if i:
                log("Red disponible tras %d segundos de espera." % (i * espera))
            return True
        except Exception:
            if i == 0:
                log("Sin red todavia (normal al despertar). Esperando…")
            time.sleep(espera)
    log("La red no volvio tras %d segundos." % (intentos * espera))
    return False


def avisar_fallo(mensaje, base=None):
    """Avisa de que una pasada ha FALLADO, por Telegram y por correo.

    Sin esto, un fallo es indistinguible de "no hay novedades": el sistema se
    quedo 4 dias sin funcionar y no se entero nadie. Se limita a un aviso cada
    6 h para no convertirlo en spam cada 2 horas.

    POR QUE TAMBIEN POR CORREO: desde el servidor, Telegram se cae a ratos
    (varios timeouts al dia contra api.telegram.org). Un aviso de averia que
    viaja solo por el canal que se puede averiar no es un aviso fiable.

    El correo NO va a los destinatarios de los oneways: va a `avisos_fallo`,
    la direccion de quien mantiene el sistema. A las oficinas no les sirve de
    nada saber que Chromium ha dado un timeout, y un aviso que no se puede
    accionar solo ensena a ignorar los avisos.
    """
    try:
        import credenciales, avisos, correo
        base = base or app_dir()
        marca = os.path.join(base, "ultimo_aviso_fallo.txt")
        ahora = datetime.datetime.now()
        if os.path.exists(marca):
            try:
                with open(marca, encoding="utf-8") as f:
                    previo = datetime.datetime.fromisoformat(f.read().strip())
                if (ahora - previo).total_seconds() < 6 * 3600:
                    registrar("Fallo repetido: no reenvio aviso (ya avise hace menos de 6 h).")
                    return False
            except Exception:
                pass

        ok_tg = False
        token, chat = credenciales.cargar_telegram(base)
        if token and chat:
            ok_tg = avisos.enviar(token, chat,
                                  "⚠️ <b>AVIS · Monitor de Oneways</b>\n"
                                  "La revisión automática ha fallado y <b>no se ha podido comprobar "
                                  "si hay oneways nuevos</b>.\n\n<code>%s</code>\n\n"
                                  "Se reintentará en la siguiente pasada." % avisos._esc(mensaje[:400]),
                                  log=registrar)
            registrar("Aviso de FALLO por Telegram: %s" % ("enviado" if ok_tg else "no enviado"))

        ok_co = False
        cfg = credenciales.cargar_correo(base)
        destino = (cfg or {}).get("avisos_fallo", "")
        if cfg and destino:
            ok_co = correo.enviar(cfg["servidor"], cfg["puerto"], cfg["usuario"],
                                  cfg["clave"], destino,
                                  "⚠️ AVIS · Monitor de Oneways — la revisión ha fallado",
                                  correo.cuerpo_fallo(mensaje[:400],
                                                      ahora.strftime("%d/%m/%Y a las %H:%M")),
                                  remitente=cfg.get("remitente") or None,
                                  log=registrar)
            registrar("Aviso de FALLO por correo a %s: %s"
                      % (destino, "enviado" if ok_co else "NO enviado"))

        # La marca se pone si el aviso SALIO POR ALGUN LADO. Si se pusiera
        # siempre, un corte de red lo silenciaria 6 h justo cuando mas falta hace.
        if ok_tg or ok_co:
            with open(marca, "w", encoding="utf-8") as f:
                f.write(ahora.isoformat(timespec="seconds"))
        return ok_tg or ok_co
    except Exception:
        return False


HORA_PARTE = 7          # no se manda el parte antes de esta hora

# OJO SI SE CAMBIA: las pasadas van a horas PARES, asi que poner aqui una hora
# impar no adelanta nada por si solo -- el parte saldria en la siguiente pasada
# que haya. Las 07:00 funcionan porque el temporizador tiene un disparador
# EXPLICITO a esa hora (oneways-pasada.timer), puesto para que el parte llegue
# justo cuando abren las oficinas.


def parte_diario(activos, base=None):
    """Una vez al día, aunque no haya cambios, manda un 'sigo vigilando'.

    POR QUE: sin esto, no recibir nada significa dos cosas —que no hay
    novedades o que lleva días parado— y desde fuera de la oficina no hay
    forma de distinguirlas. Un mensaje al día no molesta y despeja la duda.

    POR QUE NO ANTES DE LAS 8: se manda en la primera pasada correcta del día,
    y en el portátil eso caía sobre las 09:00 porque el equipo estaba dormido
    de madrugada. El servidor no duerme: su primera pasada del día es la de las
    00:00, así que el parte pasó a llegar de madrugada, cuando no le sirve a
    nadie. Es un cambio de comportamiento que introdujo la mudanza al servidor,
    no una decisión de diseño de entonces.
    """
    try:
        import credenciales, avisos
        base = base or app_dir()
        marca = os.path.join(base, "ultimo_parte.txt")
        ahora = datetime.datetime.now()
        if ahora.hour < HORA_PARTE:
            return False
        hoy = ahora.date().isoformat()
        if os.path.exists(marca):
            try:
                with open(marca, encoding="utf-8") as f:
                    if f.read().strip() == hoy:
                        return False          # ya se mandó hoy
            except Exception:
                pass
        token, chat = credenciales.cargar_telegram(base)
        if not token or not chat:
            return False
        if activos:
            detalle = "\n".join(
                _linea_oneway(r)
                for r in sorted(activos, key=lambda x: x["fecha_salida"])[:10])
            cuerpo = "Hay <b>%d oneway(s)</b> en los próximos días:\n%s" % (len(activos), detalle)
        else:
            cuerpo = "No hay ningún oneway en los próximos días."
        ok = avisos.enviar(token, chat,
                           "✅ <b>AVIS · Monitor de Oneways</b>\n"
                           "Revisión funcionando correctamente (%s).\n\n%s\n\n"
                           "<i>Reviso cada 2 horas. Solo aviso cuando hay cambios.</i>"
                           % (datetime.datetime.now().strftime("%d/%m/%Y %H:%M"), cuerpo),
                           log=registrar)
        if ok:
            with open(marca, "w", encoding="utf-8") as f:
                f.write(hoy)
        registrar("Parte diario por Telegram: %s" % ("enviado" if ok else "no enviado"))
        return ok
    except Exception:
        return False


def buscar_actualizacion(descargar=True, log=None):
    """Consulta si hay version nueva. Devuelve (manifiesto, hay_novedad)."""
    import actualizacion
    log = log or registrar
    m = actualizacion.consultar(url_actualizaciones(), log=log)
    if not m:
        return None, False
    nueva = actualizacion.hay_novedad(m["version"], VERSION)
    if nueva:
        log("Hay una version nueva: %s (tienes la %s)" % (m["version"], VERSION))
        if descargar:
            actualizacion.descargar(m, app_dir(), log=log)
    return m, nueva


# ==================== MODO ESCUCHA (comandos de Telegram) ====================
AYUDA = (
    "<b>AVIS · Monitor de Oneways</b>\n"
    "\n"
    "/revisar — reviso Rentway ahora mismo (tarda 2-3 min)\n"
    "/estado — última revisión, oneways activos y próxima pasada\n"
    "/lista — los oneways activos ahora mismo\n"
    "/ayuda — esto\n"
    "\n"
    "<i>Reviso solo cada 2 horas. Solo aviso cuando hay cambios.</i>"
)


def _ultima_pasada():
    """Fecha y hora de la última pasada que terminó bien (cada una deja un
    snapshot, así que el más reciente es la prueba de que funcionó)."""
    files = sorted(glob.glob(os.path.join(carpeta_snapshots(), "snapshot_*.json")))
    if not files:
        return None
    try:
        return datetime.datetime.strptime(
            os.path.basename(files[-1])[9:-5], "%Y-%m-%d_%H%M")
    except Exception:
        return None


def _proxima_pasada():
    """La tarea corre a las horas pares; se calcula la siguiente."""
    ahora = datetime.datetime.now()
    h = ahora.replace(minute=0, second=0, microsecond=0)
    while h <= ahora or h.hour % 2 != 0:
        h += datetime.timedelta(hours=1)
    return h


def _oneways_activos():
    """Los activos según la última foto guardada (no hace falta ir a Rentway)."""
    files = sorted(glob.glob(os.path.join(carpeta_snapshots(), "snapshot_*.json")))
    if not files:
        return []
    try:
        with open(files[-1], encoding="utf-8") as f:
            return [r for r in json.load(f).values() if r.get("activo")]
    except Exception:
        return []


def _linea_oneway(r):
    import avisos
    return "   · %s · sale %s" % (avisos.cabecera(r), avisos._esc(r.get("fecha_salida")))


def _texto_estado(base):
    import instancia
    ult = _ultima_pasada()
    L = ["<b>AVIS · Estado</b>", ""]
    if ult:
        minutos = (datetime.datetime.now() - ult).total_seconds() / 60.0
        aviso = "" if minutos < 180 else "  ⚠️ hace demasiado"
        L.append("Última revisión: <b>%s</b> (hace %s)%s"
                 % (ult.strftime("%d/%m %H:%M"), _hace(minutos), aviso))
    else:
        L.append("Última revisión: <b>ninguna todavía</b>")
    en_curso = instancia.pasada_en_curso(base)
    if en_curso:
        L.append("Ahora mismo: <b>revisando</b> (desde hace %s min)" % en_curso.get("edad_min"))
    else:
        L.append("Próxima revisión: <b>%s</b>" % _proxima_pasada().strftime("%d/%m %H:%M"))
    activos = _oneways_activos()
    L.append("Oneways activos: <b>%d</b>" % len(activos))
    L.append("")
    L.append("<i>Versión %s · equipo %s</i>" % (VERSION, instancia.yo()["equipo"]))
    return "\n".join(L)


def _hace(minutos):
    if minutos < 60:
        return "%d min" % minutos
    if minutos < 48 * 60:
        return "%.1f h" % (minutos / 60.0)
    return "%d días" % (minutos / 1440)


def _texto_lista():
    activos = _oneways_activos()
    if not activos:
        return "No hay ningún oneway activo ahora mismo."
    activos.sort(key=lambda r: r.get("fecha_salida") or "")
    L = ["<b>AVIS · %d oneway(s) activos</b>" % len(activos), ""]
    L += [_linea_oneway(r) for r in activos[:25]]
    if len(activos) > 25:
        L.append("")
        L.append("<i>… y %d más</i>" % (len(activos) - 25))
    return "\n".join(L)


def _revisar_ahora(chat_id, dias, base):
    """Hace la pasada y contesta al chat con el resultado. Va en un hilo aparte
    para que la escucha siga atendiendo comandos mientras tanto."""
    import avisos, credenciales, instancia
    token, _ = credenciales.cargar_telegram(base)
    r = ejecutar_pasada(dias, True, "telegram")
    if r["estado"] == "ok":
        n = len(r["cambios"])
        if n:
            # el aviso con el detalle ya lo ha mandado la propia pasada
            txt = "✅ Revisión terminada: <b>%d cambio(s)</b> (arriba el detalle)." % n
        else:
            txt = ("✅ Revisión terminada: <b>sin cambios</b>.\n"
                   "%d oneway(s) activos." % len(r["activos"]))
    elif r["estado"] == "ocupado":
        txt = "⏳ Ya había una revisión en curso, no lanzo otra."
    elif r["estado"] == "otro_equipo":
        txt = ("⚠️ No he revisado: está vigilando otro equipo (%s)."
               % (r["otra"] or {}).get("equipo"))
    else:
        txt = "❌ La revisión ha fallado:\n<code>%s</code>" % avisos._esc(r.get("error"))
    avisos.enviar(token, chat_id, txt, log=registrar)


def modo_escucha(dias=7):
    """Se queda escuchando comandos de Telegram hasta que se cierre.

    Es un proceso residente: arranca al iniciar sesión y no hace nada hasta que
    alguien escribe un comando. La tarea programada sigue funcionando igual.
    """
    import credenciales, avisos, escucha, instancia
    base = app_dir()
    token, chat = credenciales.cargar_telegram(base)
    if not token or not chat:
        registrar("ESCUCHA: no arranco, no hay Telegram configurado.")
        return 1

    autorizados = escucha.chats_autorizados(base, chat)
    trabajando = threading.Event()

    def atender(cmd, args, chat_id):
        if cmd in ("ayuda", "help", "start"):
            return AYUDA
        if cmd == "estado":
            return _texto_estado(base)
        if cmd == "lista":
            return _texto_lista()
        if cmd == "revisar":
            if trabajando.is_set():
                return "⏳ Ya estoy revisando, espera a que termine."
            d = dias
            if args:
                try:
                    d = max(1, min(60, int(args[0])))
                except ValueError:
                    pass
            trabajando.set()

            def tarea():
                try:
                    _revisar_ahora(chat_id, d, base)
                finally:
                    trabajando.clear()
            threading.Thread(target=tarea, daemon=True).start()
            return "🔄 Reviso Rentway ahora (%d días). Tardo 2-3 minutos…" % d
        return "No conozco ese comando. Escribe /ayuda."

    registrar("=== MODO ESCUCHA ARRANCADO (v%s) ===" % VERSION)
    threading.Thread(target=_latir_escucha, args=(base,), daemon=True).start()

    # EN UN EQUIPO DEDICADO, esta escucha es la que mantiene el equipo despierto.
    #
    # POR QUE ASI Y NO DE OTRA FORMA: el portatil es corporativo y no se puede
    # pedir que lo excluyan de la directiva de energia. Pero una POWER REQUEST
    # tiene prioridad sobre el temporizador de inactividad —es el mecanismo con
    # el que un reproductor de video impide que el equipo se duerma— asi que da
    # igual lo que diga la directiva: mientras este proceso viva, no se suspende.
    #
    # Y tiene que hacerlo LA ESCUCHA, no la pasada: la pasada solo corre cada 2
    # horas, y si el equipo ya se durmio no llega a ejecutarse nunca. Era el
    # circulo vicioso del fin de semana del 8-10/08/2026.
    guardia = None
    if os.path.exists(os.path.join(base, "equipo_dedicado.txt")):
        registrar("Equipo dedicado: mantengo el equipo despierto mientras escucho.")
        guardia = MantenerDespierto()
        guardia.__enter__()
        threading.Thread(target=_vigilar_energia, args=(base,), daemon=True).start()
    try:
        escucha.bucle(token, autorizados, atender, log=registrar,
                      responder=lambda c, t: avisos.enviar(token, c, t, log=registrar))
    except KeyboardInterrupt:
        pass
    finally:
        if guardia:
            guardia.__exit__()
    registrar("=== MODO ESCUCHA DETENIDO ===")
    return 0


def main():
    # --version va LO PRIMERO y sin efectos: es la unica forma fiable de saber
    # que version lleva dentro un .exe ya compilado (en un --onefile el codigo
    # va comprimido, asi que buscar la cadena en el binario no sirve). Se usa
    # para comprobar el build ANTES de publicarlo: si el binario y el manifiesto
    # no coinciden, todos los equipos se actualizan en bucle en cada pasada.
    #
    # Se escribe TAMBIEN en un fichero porque el .exe se compila con --windowed
    # y entonces no hay consola: el print no llega a ninguna parte.
    if "--version" in sys.argv:
        try:
            print(VERSION)
        except Exception:
            pass
        try:
            with open(os.path.join(app_dir(), "version_actual.txt"), "w",
                      encoding="utf-8") as f:
                f.write(VERSION)
        except Exception:
            pass
        return

    # Si quedo una actualizacion descargada, se aplica ANTES de nada y se
    # relanza: un .exe no puede sobrescribirse a si mismo mientras corre.
    try:
        import actualizacion
        if actualizacion.aplicar_si_toca(log=registrar):
            return
    except Exception:
        pass

    # Configuracion portable: si el clon del repositorio trae configuracion.json,
    # se vuelca al almacen cifrado de ESTE equipo. Es lo que permite clonar y
    # arrancar en un portatil nuevo sin reescribir credenciales a mano (los .dat
    # no se pueden copiar: DPAPI los ata al equipo y usuario que los creo).
    try:
        import credenciales as _cred
        for q in _cred.importar_configuracion(app_dir()):
            registrar("Configuracion importada de configuracion.json: " + q)
    except Exception as e:
        registrar("No pude importar configuracion.json: %s" % str(e)[:120])

    dias = 7
    if "--dias" in sys.argv:
        try:
            dias = int(sys.argv[sys.argv.index("--dias") + 1])
        except Exception:
            pass

    if "--probar-correo" in sys.argv:
        # Opcionalmente una direccion detras, para no molestar a la lista
        # entera mientras se comprueba una direccion nueva.
        i = sys.argv.index("--probar-correo") + 1
        destino = sys.argv[i] if i < len(sys.argv) and not sys.argv[i].startswith("-") else None
        sys.exit(0 if probar_correo(destino) else 1)

    if "--desatendido" in sys.argv:
        sys.exit(modo_desatendido(dias, "--sin-ampliados" not in sys.argv,
                                  avisar="--sin-avisos" not in sys.argv))

    if "--escucha" in sys.argv:
        sys.exit(modo_escucha(dias))

    if not HAY_TK:
        # Sin ventana y sin argumentos no hay nada que hacer, pero el mensaje
        # tiene que decir QUE falta y COMO se arregla: en un servidor esto se
        # lee en un log, no en una pantalla.
        for linea in ("No hay interfaz grafica disponible (falta Tkinter).",
                      "En un servidor usa:  --desatendido  |  --escucha",
                      "Si de verdad quieres la ventana:  apt install python3-tk"):
            print(linea, file=sys.stderr)
        return 1

    root = tk.Tk()
    try:
        root.iconbitmap(resource(os.path.join("assets", "avis.ico")))
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
