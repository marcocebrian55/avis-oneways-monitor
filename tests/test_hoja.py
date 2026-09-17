# -*- coding: utf-8 -*-
"""Pruebas de la hoja de Google: que fila sale, con que estado, color y orden,
y que el historial de 30 dias no pierde ni duplica nada."""
import os, sys, json, datetime, tempfile, shutil, unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "src"))

import hoja                       # noqa: E402
import avis_monitor as am         # noqa: E402

AHORA = datetime.datetime(2026, 9, 17, 12, 0)
ISLAS = {"TFN": "Tenerife", "TFS": "Tenerife", "LPA": "Gran Canaria"}


def reg(**kw):
    base = {"tipo": "Reserva", "num": "900", "grupo": "SC", "grupo_desc": "Economic 4",
            "matricula": "1234ABC", "salida": "TFN", "devolucion": "TFS",
            "fecha_salida": "20/09/2026 10:00", "fecha_llegada": "25/09/2026 10:00",
            "cliente": "C", "estado": "Confirmed", "activo": True}
    base.update(kw)
    return base


class EstadoTest(unittest.TestCase):
    def test_estados(self):
        casos = [
            (reg(), "Futuro"),
            (reg(fecha_salida="17/09/2026 18:00"), "Sale hoy"),
            (reg(contrato="5", estado="En curso"), "En curso"),
            (reg(contrato="5", fecha_llegada="17/09/2026 20:00"), "Se devuelve hoy"),
            (reg(contrato="5", fecha_llegada="17/09/2026 09:00"), "Atrasado"),
            # sin Abiertos pero la reserva ya dice que esta recogida
            (reg(estado="Confirmed with RA", fecha_llegada="16/09/2026 09:00"), "Atrasado"),
        ]
        for r, esperado in casos:
            self.assertEqual(hoja.estado(r, AHORA), esperado, r)

    def test_serial(self):
        # 17/09/2026 00:00 es el dia 46282 en una hoja de calculo
        self.assertEqual(hoja._serial(datetime.datetime(2026, 9, 17)), 46282.0)


class TablaTest(unittest.TestCase):
    def test_orden_colores_y_anulados_fuera(self):
        ow = {"RES-1": reg(num="1"),
              "RES-2": reg(num="2", contrato="7", fecha_llegada="17/09/2026 09:00"),
              "RES-3": reg(num="3", activo=False, estado="Canceled")}
        t = hoja.tabla_oneways(ow, ISLAS, AHORA)
        self.assertEqual([f[1] for f in t["filas"]], ["2", "1"])      # atrasado arriba
        self.assertEqual(t["colores"], ["#F8CBCB", "#DCEBFA"])
        self.assertEqual(len(t["cabecera"]), len(t["filas"][0]))
        self.assertEqual([t["cabecera"][i] for i in t["fechas"]], ["Fecha salida", "Fecha devolución"])

    def test_matricula_solo_con_contrato_e_isla(self):
        t = hoja.tabla_oneways({"RES-1": reg()}, ISLAS, AHORA)
        fila = dict(zip(t["cabecera"], t["filas"][0]))
        self.assertEqual(fila["Matrícula"], "")
        self.assertEqual((fila["Grupo"], fila["Isla salida"]), ("SC", "Tenerife"))

    def test_completados_de_avisos_y_de_silenciosos(self):
        cambios = [{"tipo": "ANULADO", "reg": reg(num="1"), "difs": [], "motivo": ""},
                   {"tipo": "NUEVO", "reg": reg(num="2"), "difs": [], "motivo": ""},
                   {"tipo": "DESAPARECIDO", "reg": reg(num="3"), "difs": [], "motivo": "MISMA_OFICINA"}]
        sil = [{"reg": reg(num="4", contrato="9"), "motivo": "TERMINADO"}]
        filas = hoja.filas_completados(cambios, sil, ISLAS, AHORA)
        motivos = sorted(f[1] for f in filas)
        self.assertEqual(len(filas), 3)
        self.assertIn("Completado (coche devuelto)", motivos)
        self.assertIn("Anulado", motivos)
        self.assertEqual(len(hoja.CAB_COMPLETADOS), len(filas[0]))
        self.assertEqual([hoja.CAB_COMPLETADOS[i] for i in (0, 10, 11)],
                         ["Cerrado", "Fecha salida", "Fecha devolución"])

    def test_comparar_devuelve_los_cierres_silenciosos(self):
        sil = []
        ayer = {"RES-1": reg(num="1", contrato="5", fecha_salida="10/09/2026 10:00")}
        self.assertEqual(am.comparar({}, ayer, silenciosos=sil), [])
        self.assertEqual([s["motivo"] for s in sil], ["TERMINADO"])


class PublicarTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def datos(self):
        with open(os.path.join(self.dir, hoja.CARPETA_PUBLICA, hoja.FICHERO_DATOS),
                  encoding="utf-8") as f:
            return json.load(f)

    def test_escribe_el_fichero_publico_y_no_deja_temporales(self):
        self.assertTrue(hoja.publicar({"RES-1": reg()}, [], [], ISLAS, self.dir, ahora=AHORA))
        d = self.datos()
        self.assertEqual(len(d["oneways"]["filas"]), 1)
        self.assertEqual(d["actualizado"], "17/09/2026 12:00")
        self.assertEqual(os.listdir(os.path.join(self.dir, hoja.CARPETA_PUBLICA)),
                         [hoja.FICHERO_DATOS])

    def test_el_historial_se_acumula_sin_duplicar_y_caduca(self):
        anulado = [{"tipo": "ANULADO", "reg": reg(num="1"), "difs": [], "motivo": ""}]
        hoja.publicar({}, anulado, [], ISLAS, self.dir, ahora=AHORA)
        dos_h = AHORA + datetime.timedelta(hours=2)
        otro = [{"tipo": "ANULADO", "reg": reg(num="2"), "difs": [], "motivo": ""}]
        hoja.publicar({}, otro, [], ISLAS, self.dir, ahora=dos_h)
        d = self.datos()
        self.assertEqual([f[2] for f in d["completados"]["filas"]], ["2", "1"])  # nuevo arriba
        self.assertEqual(len(d["alertas"]["filas"]), 2)

        # una pasada sin cambios no toca el historial
        hoja.publicar({}, [], [], ISLAS, self.dir, ahora=dos_h + datetime.timedelta(hours=2))
        self.assertEqual(len(self.datos()["completados"]["filas"]), 2)

        # a los 31 dias ya no estan
        hoja.publicar({}, [], [], ISLAS, self.dir, ahora=AHORA + datetime.timedelta(days=31))
        d = self.datos()
        self.assertEqual((d["completados"]["filas"], d["alertas"]["filas"]), ([], []))

    def test_sin_avisos_no_apunta_alertas_pero_si_completados(self):
        anulado = [{"tipo": "ANULADO", "reg": reg(), "difs": [], "motivo": ""}]
        hoja.publicar({}, anulado, [], ISLAS, self.dir, avisado=False, ahora=AHORA)
        d = self.datos()
        self.assertEqual((len(d["completados"]["filas"]), len(d["alertas"]["filas"])), (1, 0))

    def test_un_fallo_no_lanza(self):
        fichero = os.path.join(self.dir, "no_soy_carpeta")
        open(fichero, "w").close()
        self.assertFalse(hoja.publicar({}, [], [], ISLAS, fichero))

    def test_acumular_no_repite_ids(self):
        f = [46282.5, "Anulado", "x", "id1"]
        self.assertEqual(len(hoja.acumular([f], [f], 46000)), 1)


if __name__ == "__main__":
    unittest.main()
