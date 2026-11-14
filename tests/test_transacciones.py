"""Integración: los errores de escritura abortan lotes, receta y venta juntos."""

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
from pymongo.collection import Collection
from pymongo.errors import AutoReconnect, OperationFailure


class TransaccionesMongo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cliente = db.cliente()
        cls.addClassCleanup(cls.cliente.close)
        cls.cliente.admin.command("ping")
        cls.db = cls.cliente[f"farmared_test_{uuid4().hex}"]
        cls.addClassCleanup(cls.cliente.drop_database, cls.db.name)

    def setUp(self):
        for modulo in (cargar, q11, q14, q15, reglas):
            self.enterContext(patch.object(modulo, "base", return_value=self.db))
        for modulo in (q14, q15, reglas):
            self.enterContext(patch.object(modulo, "hoy", return_value=datetime(2026, 11, 14)))
        for modulo in (q14, q15):
            self.enterContext(patch.object(modulo, "proyectar", return_value=None))
        tablas = {nombre: {"catedra": cargar._leer(cargar.DATOS / nombre, nombre, True),
                           "propios": []} for nombre in cargar.ARCHIVOS}
        cargar._validar(tablas)
        with redirect_stdout(io.StringIO()):
            cargar._escribir(tablas)

    def estado(self):
        return {nombre: list(self.db[nombre].find().sort("_id", 1))
                for nombre in ("stock_lotes", "recetas", "ventas")}

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
