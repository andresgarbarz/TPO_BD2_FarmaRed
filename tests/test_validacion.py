"""Entradas inválidas de Q13/Q14/Q15 no deben escribir ni ejecutar filtros."""

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


class ValidacionEntradas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cliente = db.cliente()
        cls.addClassCleanup(cls.cliente.close)
        cls.cliente.admin.command("ping")
        cls.db = cls.cliente[f"farmared_test_{uuid4().hex}"]
        cls.addClassCleanup(cls.cliente.drop_database, cls.db.name)
        cls.tablas = {nombre: {"catedra": cargar._leer(cargar.DATOS / nombre, nombre, True),
                               "propios": []} for nombre in cargar.ARCHIVOS}

    def setUp(self):
        for modulo in (cargar, reglas, q11, q13, q14, q15):
            self.enterContext(patch.object(modulo, "base", return_value=self.db))
        for modulo in (q13, q14, q15):
            self.enterContext(patch.object(modulo, "proyectar", return_value=None))
        for modulo in (reglas, q14, q15):
            self.enterContext(patch.object(modulo, "hoy", return_value=datetime(2026, 11, 14)))
        with redirect_stdout(io.StringIO()):
            cargar._escribir(self.tablas)
        self.antes = self.estado()

    def estado(self):
        return {nombre: list(self.db[nombre].find().sort("_id", 1))
                for nombre in db.COLECCIONES}

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
