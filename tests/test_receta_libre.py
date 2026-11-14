"""Integración: las ventas libres no consumen dispensas de recetas."""

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
from consultas import q11, q14, q15


class RecetaEnVentaLibre(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cliente = db.cliente()
        cls.addClassCleanup(cls.cliente.close)
        cls.cliente.admin.command("ping")
        cls.db = cls.cliente[f"farmared_test_{uuid4().hex}"]
        cls.addClassCleanup(cls.cliente.drop_database, cls.db.name)

    def setUp(self):
        for modulo in (cargar, reglas, q11, q14, q15):
            self.enterContext(patch.object(modulo, "base", return_value=self.db))
        for modulo in (reglas, q14, q15):
            self.enterContext(patch.object(modulo, "hoy", return_value=datetime(2026, 11, 14)))
        for modulo in (q14, q15):
            self.enterContext(patch.object(modulo, "proyectar", return_value=None))
        tablas = {nombre: {"catedra": cargar._leer(cargar.DATOS / nombre, nombre, True),
                           "propios": []} for nombre in cargar.ARCHIVOS}
        with redirect_stdout(io.StringIO()):
            cargar._escribir(tablas)

    def estado(self):
        return {nombre: list(self.db[nombre].find().sort("_id", 1))
                for nombre in ("ventas", "recetas", "stock_lotes")}

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
