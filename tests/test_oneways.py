# -*- coding: utf-8 -*-
"""
Pruebas del motor: que se detecta como oneway y, sobre todo, QUE SE AVISA.

Cada caso es un fallo real o una regla que costo un aviso equivocado a las
oficinas. Si uno de estos se rompe, el siguiente despliegue manda correos
falsos a 32 personas.

    python -m unittest discover -s tests -v          (desde la raiz del repo)

Solo necesitan openpyxl. No tocan Rentway, ni el correo, ni Telegram.
"""
import os, sys, datetime, tempfile, shutil, unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "src"))

import openpyxl                   # noqa: E402
import avis_monitor as am         # noqa: E402
import avisos                     # noqa: E402
import correo                     # noqa: E402

CAB_RESERVAS = ["N.º Reserva", "Versión", "Referencia", "ID de estación de salida",
                "Oficina de salida", "Fecha de salida", "Estado", "Identificación de clientes",
                "Nombre del cliente", "Conductor", "Grupo solicitado", "ID de grupo", "Días",
                "Lugar de entrega", "Vuelo salida", "Número de matrícula", "Observaciones",
                "Tipo de cliente", "Origen", "Eliminado", "ID de estación de devolucion",
                "Oficina de devolución", "Fecha llegada"]
CAB_ABIERTOS = ["N.º Contrato", "Número de matrícula", "Grupo", "Nombre del cliente",
                "Conductor", "Fecha de salida", "Oficina de salida", "Fecha de regreso",
                "Oficina de devolución", "Días", "Contratos cerrados", "Tipo de cliente",
                "N.º Reserva", "Versión"]

AHORA = datetime.datetime.now().replace(second=0, microsecond=0)
HOY_9 = AHORA.replace(hour=9, minute=0)
AYER_9 = HOY_9 - datetime.timedelta(days=1)
DENTRO_3 = HOY_9 + datetime.timedelta(days=3)


def _txt(d):
    return d.strftime("%d/%m/%Y %H:%M")


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def excel(self, nombre, cabecera, filas):
        """Como los de Rentway: 4 filas de titulo y la cabecera en la 5."""
        wb = openpyxl.Workbook()
        sh = wb.active
        for _ in range(4):
            sh.append(["Informe"])
        sh.append(cabecera)
        for f in filas:
            sh.append([f.get(c) for c in cabecera])
        ruta = os.path.join(self.dir, nombre)
        wb.save(ruta)
        return ruta

    def reservas(self, *filas):
        base = {"Versión": 1, "Estado": "Confirmed", "Nombre del cliente": "Cliente",
                "Eliminado": False, "Fecha de salida": HOY_9, "Fecha llegada": DENTRO_3,
                "ID de grupo": "SC", "Grupo solicitado": "SC", "Número de matrícula": ""}
        return self.excel("reservations_list_x.xlsx", CAB_RESERVAS,
                          [dict(base, **f) for f in filas])

    def abiertos(self, *filas):
        base = {"Nombre del cliente": "Cliente", "Fecha de salida": HOY_9,
                "Fecha de regreso": DENTRO_3, "Grupo": "SC", "Contratos cerrados": 0}
        return self.excel("open_x.xlsx", CAB_ABIERTOS, [dict(base, **f) for f in filas])


def reserva(num, sal, dev, **kw):
    return dict({"N.º Reserva": num, "ID de estación de salida": sal,
                 "ID de estación de devolucion": dev}, **kw)


def contrato(num, res, sal, dev, **kw):
    return dict({"N.º Contrato": num, "N.º Reserva": res, "Oficina de salida": sal + " Oficina",
                 "Oficina de devolución": dev + " Oficina", "Número de matrícula": "1234ABC"}, **kw)


class LecturaTest(Base):
    def test_reserva_y_contrato_son_el_mismo_oneway(self):
        ow = am.leer_oneways(self.reservas(reserva(900, "LPA", "ALP4")),
                             self.abiertos(contrato(590, 900, "LPA", "ALP4", Grupo="SC1")))
        self.assertEqual(list(ow), ["RES-900"])
        r = ow["RES-900"]
        self.assertEqual((r["contrato"], r["estado"], r["matricula"]), ("590", "En curso", "1234ABC"))
        self.assertEqual(r["grupo"], "SC")            # el reservado, no el del coche
        self.assertEqual(r["grupo_coche"], "SC1")

    def test_contrato_que_vuelve_a_la_misma_oficina_da_de_baja(self):
        no = set()
        ow = am.leer_oneways(self.reservas(reserva(900, "LPA", "ALP4")),
                             self.abiertos(contrato(590, 900, "LPA", "LPA")), no)
        self.assertEqual(ow, {})
        self.assertEqual(no, {"RES-900"})

    def test_contrato_con_reserva_fuera_de_ventana_usa_la_clave_de_la_reserva(self):
        ow = am.leer_oneways(self.reservas(), self.abiertos(contrato(590, 900, "TFN", "TFS")))
        self.assertEqual(list(ow), ["RES-900"])
        self.assertEqual((ow["RES-900"]["tipo"], ow["RES-900"]["num"]), ("Reserva", "900"))

    def test_contrato_sin_reserva_se_vigila_como_contrato(self):
        ow = am.leer_oneways(self.reservas(), self.abiertos(contrato(591, None, "TFN", "TFS")))
        self.assertEqual(list(ow), ["CON-591"])

    def test_dato_incompleto_no_da_de_baja(self):
        ow = am.leer_oneways(self.reservas(reserva(900, "LPA", "ALP4")),
                             self.abiertos(contrato(590, 900, "LPA", "", **{"Oficina de devolución": None})))
        self.assertIn("RES-900", ow)
        self.assertFalse(ow["RES-900"].get("contrato"))

    def test_codigo_de_oficina_con_espacio_se_conserva_entero(self):
        # 21/09/2026: 'TFN BUD' se quedaba en 'TFN', que es la oficina de AVIS.
        ow = am.leer_oneways(self.reservas(reserva(900, "TFN BUD", "TFSBUD")),
                             self.abiertos(contrato(591, None, "FUE TUR", "TFN BUD")))
        self.assertEqual((ow["RES-900"]["salida"], ow["RES-900"]["devolucion"]), ("TFN BUD", "TFSBUD"))
        self.assertEqual((ow["CON-591"]["salida"], ow["CON-591"]["devolucion"]), ("FUE TUR", "TFN BUD"))

    def test_budget_y_avis_del_mismo_aeropuerto_son_oneway(self):
        ow = am.leer_oneways(self.reservas(reserva(900, "TFN BUD", "TFN")),
                             self.abiertos(contrato(591, None, "TFN", "TFN BUD")))
        self.assertEqual(sorted(ow), ["CON-591", "RES-900"])

    def test_formato_cambiado_se_detecta(self):
        cab = [c if c != "Oficina de salida" else "ID de la oficina" for c in CAB_ABIERTOS]
        f = {"reservas": self.reservas(reserva(1, "A", "B")),
             "abiertos": self.excel("open_y.xlsx", cab, [])}
        problemas = am.comprobar_formato(f)
        self.assertEqual(len(problemas), 1)
        self.assertIn("Oficina de salida", problemas[0])


def reg(**kw):
    base = {"tipo": "Reserva", "num": "900", "grupo": "SC", "matricula": "", "salida": "LPA",
            "devolucion": "ALP4", "fecha_salida": _txt(HOY_9), "fecha_llegada": _txt(DENTRO_3),
            "cliente": "C", "estado": "Confirmed", "activo": True}
    base.update(kw)
    return base


class AvisosTest(unittest.TestCase):
    def tipos(self, hoy, ayer, **kw):
        return [(c["tipo"], c["motivo"]) for c in am.comparar(hoy, ayer, **kw)]

    def test_nuevo(self):
        self.assertEqual(self.tipos({"RES-900": reg()}, {}), [("NUEVO", "")])

    def test_reserva_ya_anulada_que_entra_en_la_ventana_no_es_nueva(self):
        self.assertEqual(self.tipos({"RES-900": reg(estado="Canceled by Client", activo=False)}, {}), [])

    def test_anulacion(self):
        self.assertEqual(self.tipos({"RES-900": reg(estado="Canceled by Operator", activo=False)},
                                    {"RES-900": reg()}), [("ANULADO", "")])

    def test_anulada_que_sale_de_la_ventana_no_se_repite(self):
        self.assertEqual(self.tipos({}, {"RES-900": reg(estado="Canceled", activo=False)}), [])

    def test_medianoche_no_es_una_baja(self):
        # La Reserva 900 del 26/08/2026 a las 00:08.
        ayer = {"RES-900": reg(fecha_salida=_txt(AYER_9))}
        self.assertEqual(self.tipos({}, ayer), [])

    def test_contrato_cerrado_no_es_una_baja(self):
        ayer = {"RES-900": reg(contrato="590", estado="En curso", fecha_salida=_txt(AYER_9))}
        self.assertEqual(self.tipos({}, ayer), [])

    def test_desaparece_dentro_de_la_ventana_si_se_avisa(self):
        self.assertEqual(self.tipos({}, {"RES-900": reg()}), [("DESAPARECIDO", "")])

    def test_devolucion_cambiada_a_la_misma_oficina_si_se_avisa(self):
        ayer = {"RES-900": reg(contrato="590", estado="En curso")}
        self.assertEqual(self.tipos({}, ayer, no_oneway={"RES-900"}),
                         [("DESAPARECIDO", "MISMA_OFICINA")])

    def test_contrato_anulado(self):
        ayer = {"RES-900": reg(contrato="590", estado="En curso")}
        self.assertEqual(self.tipos({}, ayer, anulados={"590": "x"}), [("DESAPARECIDO", "ANULADO")])

    def test_recogida(self):
        hoy = {"RES-900": reg(contrato="590", estado="En curso", matricula="1234ABC")}
        self.assertEqual(self.tipos(hoy, {"RES-900": reg()}), [("EN_CURSO", "")])

    def test_matricula_antes_de_la_entrega_no_avisa(self):
        self.assertEqual(self.tipos({"RES-900": reg(matricula="5008NFG")}, {"RES-900": reg()}), [])

    def test_cambio_de_coche_con_contrato_si_avisa(self):
        ayer = {"RES-900": reg(contrato="590", estado="En curso", matricula="1111AAA")}
        hoy = {"RES-900": reg(contrato="590", estado="En curso", matricula="2222BBB")}
        self.assertEqual(self.tipos(hoy, ayer), [("CAMBIO", "")])

    def test_cambio_de_grupo_avisa(self):
        self.assertEqual(self.tipos({"RES-900": reg(grupo="SG")}, {"RES-900": reg()}), [("CAMBIO", "")])

    def test_foto_antigua_sin_grupo_no_avisa_a_todos(self):
        viejo = reg()
        del viejo["grupo"]
        self.assertEqual(self.tipos({"RES-900": reg()}, {"RES-900": viejo}), [])

    def test_foto_con_la_oficina_cortada_no_avisa_de_cambio(self):
        ayer = {"RES-900": reg(salida="TFN", devolucion="TFSBUD")}
        hoy = {"RES-900": reg(salida="TFN BUD", devolucion="TFSBUD", codigo_entero=True)}
        self.assertEqual(self.tipos(hoy, ayer), [])

    def test_cambio_de_oficina_con_la_foto_nueva_si_avisa(self):
        ayer = {"RES-900": reg(salida="TFN", devolucion="TFSBUD", codigo_entero=True)}
        hoy = {"RES-900": reg(salida="TFN BUD", devolucion="TFSBUD", codigo_entero=True)}
        self.assertEqual(self.tipos(hoy, ayer), [("CAMBIO", "")])


class RepartoTest(unittest.TestCase):
    MAPA = {"TFN": "Tenerife", "TFS": "Tenerife", "ACE": "Lanzarote",
            "XTK6": "Tenerife", "XACE": "Lanzarote", "VDE": "El Hierro"}
    ISLAS = {"Tenerife": "tf@a", "Lanzarote": "lz@a"}
    XTRA = {"X": "admin@xtravans"}

    def quien(self, sal, dev, por_prefijo=None, por_isla=None):
        c = {"tipo": "NUEVO", "reg": reg(salida=sal, devolucion=dev)}
        lotes, huerfanas = am.repartir([c], ["jefe@a"], self.ISLAS if por_isla is None else por_isla,
                                       self.MAPA, por_prefijo)
        return sorted(g for gente, _ in lotes for g in gente), huerfanas

    def test_por_islas_como_siempre(self):
        self.assertEqual(self.quien("TFN", "ACE")[0], ["jefe@a", "lz@a", "tf@a"])

    def test_xtravans_solo_a_su_equipo(self):
        self.assertEqual(self.quien("XACE", "XTK6", self.XTRA)[0], ["admin@xtravans", "jefe@a"])

    def test_xtravans_no_recibe_los_de_avis(self):
        self.assertEqual(self.quien("TFN", "TFS", self.XTRA)[0], ["jefe@a", "tf@a"])

    def test_mixto_avisa_a_las_dos_oficinas(self):
        self.assertEqual(self.quien("XTK6", "TFS", self.XTRA)[0], ["admin@xtravans", "jefe@a", "tf@a"])

    def test_prefijo_sin_lista_vuelve_a_la_isla(self):
        self.assertEqual(self.quien("XACE", "XTK6", {"X": ""})[0], ["jefe@a", "lz@a", "tf@a"])

    def test_sin_islas_el_prefijo_sigue_funcionando(self):
        self.assertEqual(self.quien("XACE", "TFN", self.XTRA, por_isla={})[0], ["admin@xtravans", "jefe@a"])

    def test_isla_sin_lista_va_a_todos_incluido_xtravans(self):
        quien, huerfanas = self.quien("VDE", "TFN", self.XTRA)
        self.assertEqual(quien, ["admin@xtravans", "jefe@a", "lz@a", "tf@a"])
        self.assertEqual(huerfanas, ["El Hierro"])


class ContinuidadTest(Base):
    def test_un_oneway_recogido_sobrevive_a_la_medianoche(self):
        """Dia 1: reserva + contrato. Dia 2: la reserva ya no esta en la ventana
        y solo queda el contrato. No puede salir ningun aviso."""
        dia1 = am.leer_oneways(self.reservas(reserva(900, "LPA", "ALP4", **{"Fecha de salida": AYER_9})),
                               self.abiertos(contrato(590, 900, "LPA", "ALP4", **{"Fecha de salida": AYER_9})))
        dia2 = am.leer_oneways(self.reservas(),
                               self.abiertos(contrato(590, 900, "LPA", "ALP4", **{"Fecha de salida": AYER_9})))
        am.conservar_conocidos(dia2, dia1)
        self.assertEqual(am.comparar(dia2, dia1), [])
        self.assertEqual(dia2["RES-900"]["grupo"], "SC")

    def test_sin_abiertos_se_conserva_el_contrato_de_un_coche_que_salio_ayer(self):
        ayer = {"RES-900": dict(reg(contrato="590", estado="En curso", fecha_salida=_txt(AYER_9)),
                                _de_contrato=["contrato", "estado", "fecha_salida"])}
        ow = {}
        am.arrastrar_contratos(ow, ayer)
        self.assertIn("RES-900", ow)
        self.assertEqual(am.comparar(ow, ayer), [])

    def test_sin_abiertos_no_se_resucita_una_reserva_de_hoy_que_ha_desaparecido(self):
        ayer = {"RES-900": dict(reg(contrato="590", estado="En curso"),
                                _de_contrato=["contrato", "estado"])}
        ow = {}
        am.arrastrar_contratos(ow, ayer)
        self.assertEqual(ow, {})


class MensajeTest(unittest.TestCase):
    def test_grupo_delante_y_sin_matricula_antes_de_la_entrega(self):
        r = reg(matricula="5008NFG", grupo_desc="Economic 4")
        t = avisos.cabecera(r)
        self.assertIn("grupo <b>SC</b> (Economic 4)", t)
        self.assertNotIn("5008NFG", t)

    def test_con_contrato_sale_la_matricula_despues_del_grupo(self):
        r = reg(matricula="5008NFG", contrato="590", grupo_coche="SC1")
        t = avisos.cabecera(r)
        self.assertLess(t.index("SC"), t.index("5008NFG"))
        self.assertIn("coche de grupo SC1", t)

    def test_los_tres_mensajes_se_componen(self):
        cambios = [{"tipo": t, "reg": reg(), "difs": [("grupo", "SC", "SG")], "motivo": m}
                   for t, m in (("NUEVO", ""), ("ANULADO", ""), ("EN_CURSO", ""), ("CAMBIO", ""),
                                ("DESAPARECIDO", "MISMA_OFICINA"))]
        self.assertIn("ANULADO", avisos.texto_cambios(cambios, [], "x"))
        self.assertIn("misma oficina", correo.cuerpo_cambios(cambios, [], "x"))
        self.assertEqual(am._asunto_cambios(cambios),
                         "AVIS · 1 oneway NUEVO, 1 anulado, 1 baja, 1 recogido, 1 cambio")

    def test_descripcion_de_grupo(self):
        self.assertEqual(am.descripcion_grupo("SC"), "Economic 4")
        self.assertEqual(am.descripcion_grupo("NOEXISTE"), "")


if __name__ == "__main__":
    unittest.main()
