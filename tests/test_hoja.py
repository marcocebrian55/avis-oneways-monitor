# -*- coding: utf-8 -*-
"""Pruebas de la hoja de Google: que fila sale, con que estado, color y orden,
y que no se pierde ni se duplica nada cuando el envio falla."""
import os, sys, datetime, tempfile, shutil, unittest

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

    def test_sin_avisos_no_apunta_alertas(self):
        cambios = [{"tipo": "NUEVO", "reg": reg(), "difs": [], "motivo": ""}]
        self.assertEqual(hoja.construir({}, cambios, [], ISLAS, False, AHORA)["nuevas_alertas"], [])
        self.assertEqual(len(hoja.construir({}, cambios, [], ISLAS, True, AHORA)["nuevas_alertas"]), 1)

    def test_comparar_devuelve_los_cierres_silenciosos(self):
        sil = []
        ayer = {"RES-1": reg(num="1", contrato="5", fecha_salida="10/09/2026 10:00")}
        self.assertEqual(am.comparar({}, ayer, silenciosos=sil), [])
        self.assertEqual([s["motivo"] for s in sil], ["TERMINADO"])


class EnvioTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ["HOJA_URL"], os.environ["HOJA_CLAVE"] = "https://x/exec", "secreto"
        self.enviar_original = hoja.enviar
        self.enviados = []

    def tearDown(self):
        hoja.enviar = self.enviar_original
        del os.environ["HOJA_URL"], os.environ["HOJA_CLAVE"]
        shutil.rmtree(self.dir, ignore_errors=True)

    def _cambios(self, n):
        return [{"tipo": "ANULADO", "reg": reg(num=str(n)), "difs": [], "motivo": ""}]

    def test_sin_configurar_no_hace_nada(self):
        del os.environ["HOJA_URL"]
        os.environ["HOJA_URL"] = ""
        self.assertIsNone(hoja.sincronizar({}, [], [], ISLAS, self.dir))

    def test_si_falla_se_reenvia_en_la_siguiente(self):
        def falla(url, cuerpo, timeout=90):
            raise OSError("sin red")
        hoja.enviar = falla
        self.assertFalse(hoja.sincronizar({}, self._cambios(1), [], ISLAS, self.dir, ahora=AHORA))

        def ok(url, cuerpo, timeout=90):
            self.enviados.append(cuerpo)
            return {"ok": True}
        hoja.enviar = ok
        self.assertTrue(hoja.sincronizar({}, self._cambios(2), [], ISLAS, self.dir,
                                         ahora=AHORA + datetime.timedelta(hours=2)))
        c = self.enviados[0]
        self.assertEqual(c["clave"], "secreto")
        self.assertEqual(len(c["completados"]["filas"]), 2)     # el que fallo + el nuevo
        self.assertEqual(len(c["alertas"]["filas"]), 2)
        self.assertFalse(os.path.exists(os.path.join(self.dir, hoja.COLA)))

    def test_respuesta_con_error_cuenta_como_fallo(self):
        hoja.enviar = lambda url, cuerpo, timeout=90: {"ok": False, "error": "clave incorrecta"}
        self.assertFalse(hoja.sincronizar({}, self._cambios(1), [], ISLAS, self.dir, ahora=AHORA))
        self.assertTrue(os.path.exists(os.path.join(self.dir, hoja.COLA)))


if __name__ == "__main__":
    unittest.main()
