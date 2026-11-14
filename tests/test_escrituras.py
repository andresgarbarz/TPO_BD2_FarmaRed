"""Regresiones de Q13/Q14/Q15: entradas, recetas y rechazo sin cambios."""

import io
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

RAIZ = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RAIZ / "src"), str(RAIZ / "scripts")]

import cargar
import db
import reglas
from consultas import q11, q13, q14, q15
from pymongo.collection import Collection
from pymongo.errors import AutoReconnect, OperationFailure


class EscriturasMongo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cliente = db.cliente()
        cls.addClassCleanup(cls.cliente.close)
        cls.cliente.admin.command("ping")
        cls.db = cls.cliente[f"farmared_test_{uuid4().hex}"]
        cls.addClassCleanup(cls.cliente.drop_database, cls.db.name)

    def setUp(self):
        for modulo in (cargar, q11, q13, q14, q15, reglas):
            self.enterContext(patch.object(modulo, "base", return_value=self.db))
        for modulo in (q14, q15, reglas):
            self.enterContext(patch.object(modulo, "hoy", return_value=datetime(2026, 11, 14)))
        for modulo in (q13, q14, q15):
            self.enterContext(patch.object(modulo, "proyectar", return_value=None))
        tablas = {nombre: {"catedra": cargar._leer(cargar.DATOS / nombre, nombre, True),
                           "propios": []} for nombre in cargar.ARCHIVOS}
        cargar._validar(tablas)
        with redirect_stdout(io.StringIO()):
            cargar._escribir(tablas)
        self.antes = self.estado()

    def estado(self):
        return {nombre: list(self.db[nombre].find().sort("_id", 1))
                for nombre in db.COLECCIONES}

    def test_error_segundo_lote_aborta_primer_lote(self):
        antes = self.estado()
        original = Collection.update_one
        llamadas = []

        def fallar(coleccion, filtro, cambio, *args, **kwargs):
            if (coleccion.database.name == self.db.name and coleccion.name == "stock_lotes"
                    and cambio.get("$inc", {}).get("unidades", 0) < 0):
                llamadas.append(filtro["_id"])
                if filtro["_id"] == "L015":
                    raise AutoReconnect("fallo antes de escribir el segundo lote")
            return original(coleccion, filtro, cambio, *args, **kwargs)

        with patch.object(Collection, "update_one", fallar):
            respuesta = q14.ejecutar("C006", "F001", [{"id_producto": "PRD003", "cantidad": 50}],
                                    "Obra social", "RC003")
        self.assertFalse(respuesta["ok"], respuesta)
        self.assertEqual(llamadas, ["L005", "L015"])
        self.assertEqual(self.estado(), antes)

    def test_error_insercion_aborta_lotes_y_receta(self):
        antes = self.estado()
        with patch.object(q14, "_insertar_venta", side_effect=OperationFailure("fallo de inserción")):
            respuesta = q14.ejecutar("C006", "F001", [{"id_producto": "PRD003", "cantidad": 50}],
                                    "Obra social", "RC003")
        self.assertFalse(respuesta["ok"], respuesta)
        self.assertEqual(self.estado(), antes)

    def test_error_completar_aborta_stock_y_receta(self):
        antes = self.estado()
        original = Collection.update_one

        def fallar(coleccion, filtro, cambio, *args, **kwargs):
            if (coleccion.database.name == self.db.name and coleccion.name == "ventas"
                    and filtro.get("_id") == "V011"):
                raise OperationFailure("fallo al completar la venta")
            return original(coleccion, filtro, cambio, *args, **kwargs)

        with patch.object(Collection, "update_one", fallar):
            respuesta = q15.ejecutar("V011")
        self.assertFalse(respuesta["ok"], respuesta)
        self.assertEqual(self.estado(), antes)

    def test_error_transitorio_reintenta_transaccion_completa(self):
        original = Collection.update_one
        fallo = False

        def fallar_una_vez(coleccion, filtro, cambio, *args, **kwargs):
            nonlocal fallo
            if (not fallo and coleccion.database.name == self.db.name
                    and coleccion.name == "ventas" and filtro.get("_id") == "V011"):
                fallo = True
                raise OperationFailure("conflicto transitorio", code=112,
                                       details={"errorLabels": ["TransientTransactionError"]})
            return original(coleccion, filtro, cambio, *args, **kwargs)

        with patch.object(Collection, "update_one", fallar_una_vez):
            respuesta = q15.ejecutar("V011")
        self.assertTrue(fallo)
        self.assertTrue(respuesta["ok"], respuesta)
        self.assertEqual(self.db.stock_lotes.find_one({"_id": "L014"})["unidades"], 44)
        self.assertEqual(self.db.recetas.find_one({"_id": "RC006"})["dispensas_realizadas"], 1)

    def rechaza_sin_escribir(self, respuesta):
        self.assertFalse(respuesta["ok"], respuesta)
        self.assertIsInstance(respuesta["error"], str)
        self.assertEqual(self.estado(), self.antes)

    def venta(self, **cambios):
        datos = {"id_cliente": "C001", "id_farmaceutico": "F001",
                 "items": [{"id_producto": "PRD001", "cantidad": 1}], "medio_pago": "Efectivo"}
        datos.update(cambios)
        return q14.ejecutar(**datos)

    def test_ids_no_admiten_operadores_ni_otros_tipos(self):
        for valor in ({"$ne": None}, ["C001"], None, 1, True, "", "   "):
            with self.subTest(valor=valor):
                self.rechaza_sin_escribir(q13.ejecutar("baja", id_cliente=valor))
                self.rechaza_sin_escribir(q13.ejecutar("modificar", id_cliente=valor, telefono="123"))
                self.rechaza_sin_escribir(self.venta(id_cliente=valor))
                self.rechaza_sin_escribir(self.venta(id_farmaceutico=valor))
                self.rechaza_sin_escribir(q15.ejecutar(valor))
        for valor in ({"$ne": None}, ["RC001"], 1, True, "", "   "):
            with self.subTest(receta=valor):
                self.rechaza_sin_escribir(self.venta(id_receta=valor))

    def test_items_incompletos_o_de_otro_tipo(self):
        for items in (None, {}, "PRD001", [], [None], ["PRD001"], [{}],
                      [{"id_producto": "PRD001"}], [{"cantidad": 1}],
                      [{"id_producto": {"$ne": None}, "cantidad": 1}]):
            with self.subTest(items=items):
                self.rechaza_sin_escribir(self.venta(items=items))

    def test_cantidad_debe_ser_entera_positiva(self):
        for cantidad in (1.5, float("nan"), float("inf"), True, False, "1", None, [], 0, -1, 2 ** 63):
            with self.subTest(cantidad=cantidad):
                self.rechaza_sin_escribir(self.venta(items=[{"id_producto": "PRD001", "cantidad": cantidad}]))

    def test_total_fuera_de_rango_se_rechaza_sin_cambios(self):
        self.db.productos.update_one({"_id": "PRD001"}, {"$set": {"precio_unit": 2 ** 62}})
        self.antes = self.estado()
        self.rechaza_sin_escribir(self.venta(items=[{"id_producto": "PRD001", "cantidad": 2}]))

    def test_cliente_y_contacto_necesitan_textos(self):
        datos = {"nombre": "Ana", "apellido": "Prueba", "dni": "30111222",
                 "email": "ana@example.test", "telefono": "123", "ciudad": "CABA",
                 "provincia": "Buenos Aires", "obra_social": "Sin cobertura"}
        for campo in q13.ALTA:
            for valor in ({"$ne": None}, [], True, 123, "   "):
                with self.subTest(campo=campo, valor=valor):
                    self.rechaza_sin_escribir(q13.ejecutar("alta", **{**datos, campo: valor}))
        for campo in q13.CONTACTO:
            for valor in ({}, [], True, 123, "   "):
                with self.subTest(campo=campo, valor=valor):
                    self.rechaza_sin_escribir(q13.ejecutar("modificar", id_cliente="C001", **{campo: valor}))

    def test_campos_validos_conservan_el_contrato(self):
        respuesta = q13.ejecutar("alta", nombre="Ana", apellido="Prueba", dni="30111222",
            email="ana@example.test", telefono="123", ciudad="CABA", provincia="Buenos Aires",
            obra_social="Sin cobertura", nro_afiliado=None)
        self.assertTrue(respuesta["ok"], respuesta)
        self.assertEqual(respuesta["documento"]["dni"], "30111222")
        self.assertIsNone(respuesta["documento"]["nro_afiliado"])
        self.assertTrue(q13.ejecutar("modificar", id_cliente="C001", telefono="456")["ok"])
        self.assertTrue(self.venta()["ok"])

    def test_q14_rechaza_receta_en_venta_libre_sin_cambios(self):
        antes = self.estado()
        respuesta = q14.ejecutar("C006", "F001", [{"id_producto": "PRD001", "cantidad": 1}],
                                "Efectivo", "RC004")
        self.assertFalse(respuesta["ok"], respuesta)
        self.assertIn("venta libre", respuesta["error"])
        self.assertEqual(self.estado(), antes)

    def test_q14_libre_sin_receta_no_modifica_dispensas(self):
        recetas = self.estado()["recetas"]
        respuesta = q14.ejecutar("C006", "F001", [{"id_producto": "PRD001", "cantidad": 1}],
                                "Efectivo")
        self.assertTrue(respuesta["ok"], respuesta)
        self.assertEqual(respuesta["documento"]["tipo"], "Venta libre")
        self.assertIsNone(respuesta["documento"]["id_receta"])
        self.assertEqual(self.estado()["recetas"], recetas)

    def test_q14_mixta_usa_una_sola_dispensa(self):
        respuesta = q14.ejecutar("C006", "F001", [
            {"id_producto": "PRD001", "cantidad": 1},
            {"id_producto": "PRD003", "cantidad": 1},
        ], "Efectivo", "RC004")
        self.assertTrue(respuesta["ok"], respuesta)
        self.assertEqual(respuesta["documento"]["tipo"], "Con receta")
        self.assertEqual(respuesta["documento"]["id_receta"], "RC004")
        self.assertEqual(respuesta["documento"]["total"], 12600)
        self.assertEqual(self.db.recetas.find_one({"_id": "RC004"})["dispensas_realizadas"], 2)

    def test_q15_rechaza_pendiente_libre_con_receta_sin_cambios(self):
        self.db.ventas.update_one({"_id": "V012"}, {"$set": {
            "id_cliente": "C006", "id_receta": "RC004", "total": 2800,
            "items": [{"id_detalle": "DX", "id_producto": "PRD001",
                       "cantidad": 1, "precio_unit": 2800}],
        }})
        antes = self.estado()
        respuesta = q15.ejecutar("V012")
        self.assertFalse(respuesta["ok"], respuesta)
        self.assertIn("venta libre", respuesta["error"])
        self.assertEqual(self.estado(), antes)
