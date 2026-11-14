"""Integración: completar una pendiente no cambia su sucursal histórica."""

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
from consultas import q11, q15


class SucursalHistorica(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cliente = db.cliente()
        cls.addClassCleanup(cls.cliente.close)
        cls.cliente.admin.command("ping")
        cls.db = cls.cliente[f"farmared_test_{uuid4().hex}"]
        cls.addClassCleanup(cls.cliente.drop_database, cls.db.name)

    def setUp(self):
        for modulo in (cargar, q11, q15, reglas):
            self.enterContext(patch.object(modulo, "base", return_value=self.db))
        for modulo in (q15, reglas):
            self.enterContext(patch.object(modulo, "hoy", return_value=datetime(2026, 11, 14)))
        self.proyectar = self.enterContext(patch.object(q15, "proyectar", return_value=None))
        tablas = {nombre: {"catedra": cargar._leer(cargar.DATOS / nombre, nombre, True),
                           "propios": []} for nombre in cargar.ARCHIVOS}
        with redirect_stdout(io.StringIO()):
            cargar._escribir(tablas)

    def reasignar_farmaceutico(self):
        self.db.farmaceuticos.update_one({"_id": "F006"}, {"$set": {"id_sucursal": "S001"}})
        lote = self.db.stock_lotes.find_one({"_id": "L014"})
        lote.update({"_id": "LX001", "id_lote": "LX001", "id_sucursal": "S001"})
        self.db.stock_lotes.insert_one(lote)

    def test_rechaza_reasignacion_sin_modificar_ninguna_coleccion(self):
        self.reasignar_farmaceutico()
        antes = {nombre: list(self.db[nombre].find().sort("_id", 1))
                 for nombre in db.COLECCIONES}
        respuesta = q15.ejecutar("V011")
        self.assertFalse(respuesta["ok"], respuesta)
        self.assertIn("sucursal registrada", respuesta["error"])
        self.assertEqual(antes, {nombre: list(self.db[nombre].find().sort("_id", 1))
                                 for nombre in db.COLECCIONES})
        self.proyectar.assert_not_called()

    def test_completa_en_la_sucursal_registrada(self):
        respuesta = q15.ejecutar("V011")
        self.assertTrue(respuesta["ok"], respuesta)
        self.assertEqual(respuesta["documento"]["id_sucursal"], "S004")
        self.assertEqual(respuesta["documento"]["fecha_registro"], datetime(2026, 10, 12))
        self.assertEqual(self.db.stock_lotes.find_one({"_id": "L014"})["unidades"], 44)
        self.assertEqual(self.db.recetas.find_one({"_id": "RC006"})["estado"], "Completada")

    def test_venta_sin_sucursal_guardada_usa_la_actual(self):
        self.db.ventas.update_one({"_id": "V011"}, {"$unset": {"id_sucursal": ""}})
        self.reasignar_farmaceutico()
        respuesta = q15.ejecutar("V011")
        self.assertTrue(respuesta["ok"], respuesta)
        self.assertEqual(respuesta["documento"]["id_sucursal"], "S001")
        self.assertEqual(self.db.stock_lotes.find_one({"_id": "L014"})["unidades"], 45)
        self.assertEqual(self.db.stock_lotes.find_one({"_id": "LX001"})["unidades"], 44)
