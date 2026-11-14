"""Integración concurrente de Q15 contra MongoDB real con replica set."""

import io
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

RAIZ = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RAIZ / "src"), str(RAIZ / "scripts")]

import cargar
import db
import reglas
from consultas import q11, q15
from pymongo.collection import Collection

HOY = datetime(2026, 11, 14)


class ConcurrenciaMongo(unittest.TestCase):
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
        for modulo in (cargar, q11, q15, reglas):
            self.enterContext(patch.object(modulo, "base", return_value=self.db))
        for modulo in (q15, reglas):
            self.enterContext(patch.object(modulo, "hoy", return_value=HOY))
        self.enterContext(patch.object(q15, "proyectar", return_value=None))
        self.cargar()

    def cargar(self):
        with redirect_stdout(io.StringIO()):
            cargar._escribir(self.tablas)
        self.db.ventas.update_one({"_id": "V011"},
                                 {"$set": {"id_cliente": "C006", "id_receta": "RC004"}})

    def completar_juntos(self, ids):
        original = Collection.find_one
        primera = threading.local()
        barrera = threading.Barrier(2)
        lecturas = []

        def leer_juntos(coleccion, filtro, *args, **kwargs):
            documento = original(coleccion, filtro, *args, **kwargs)
            if (coleccion.database.name == self.db.name and coleccion.name == "ventas"
                    and filtro.get("_id") in ids and not getattr(primera, "vista", False)):
                primera.vista = True
                lecturas.append(documento["estado"])
                # Ambos fijan su snapshot antes de escribir; los reintentos no esperan.
                barrera.wait(timeout=10)
            return documento

        with patch.object(Collection, "find_one", leer_juntos):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futuros = [executor.submit(q15.ejecutar, id_venta) for id_venta in ids]
                respuestas = [futuro.result(timeout=30) for futuro in futuros]
        self.assertEqual(lecturas, ["Pendiente", "Pendiente"])
        return respuestas

    def test_misma_venta_solo_consume_una_dispensa_y_una_unidad(self):
        respuestas = self.completar_juntos(["V011", "V011"])
        self.assertEqual(sum(r["ok"] for r in respuestas), 1, respuestas)
        venta = self.db.ventas.find_one({"_id": "V011"})
        self.assertEqual(venta["estado"], "Completada")
        self.assertEqual(venta["fecha"], HOY)
        self.assertEqual(venta["fecha_registro"], datetime(2026, 10, 12))
        self.assertEqual(venta["items"][0]["lotes"], [{"id_lote": "L014", "unidades": 1}])
        self.assertEqual(self.db.stock_lotes.find_one({"_id": "L014"})["unidades"], 44)
        receta = self.db.recetas.find_one({"_id": "RC004"})
        self.assertEqual(receta["dispensas_realizadas"], 2)
        self.assertEqual(receta["estado"], "Vigente")
        self.assertEqual(receta["proxima_dispensa"], HOY + timedelta(days=30))
        self.assertEqual(self.db.ventas.count_documents({}), 16)

    def test_ventas_distintas_respetan_stock_fefo_y_dispensas_disponibles(self):
        for unidades, hechas, exitos in ((2, 1, 2), (1, 1, 1), (2, 2, 1)):
            with self.subTest(unidades=unidades, dispensas_iniciales=hechas):
                self.cargar()
                venta = self.db.ventas.find_one({"_id": "V011"})
                venta["_id"] = venta["id_venta"] = "VX001"
                venta["items"][0]["id_detalle"] = "DX001"
                self.db.ventas.insert_one(venta)
                self.db.recetas.update_one({"_id": "RC004"},
                                           {"$set": {"dispensas_realizadas": hechas}})
                self.db.stock_lotes.update_one({"_id": "L014"}, {"$set": {
                    "unidades": 1, "vencimiento": HOY + timedelta(days=1)}})
                lote = self.db.stock_lotes.find_one({"_id": "L014"})
                self.db.stock_lotes.insert_one({**lote, "_id": "LX001", "id_lote": "LX001",
                    "unidades": unidades - 1, "vencimiento": HOY + timedelta(days=2)})
                self.db.stock_lotes.insert_one({**lote, "_id": "LX000", "id_lote": "LX000",
                    "unidades": 100, "vencimiento": HOY - timedelta(days=1)})
                antes = {v["_id"]: v for v in self.db.ventas.find({"_id": {"$in": ["V011", "VX001"]}})}

                respuestas = self.completar_juntos(["V011", "VX001"])
                self.assertEqual(sum(r["ok"] for r in respuestas), exitos, respuestas)
                for id_venta, respuesta in zip(["V011", "VX001"], respuestas):
                    actual = self.db.ventas.find_one({"_id": id_venta})
                    if respuesta["ok"]:
                        self.assertEqual(actual["estado"], "Completada")
                        self.assertEqual(actual["fecha_registro"], datetime(2026, 10, 12))
                    else:
                        self.assertEqual(actual, antes[id_venta])
                receta = self.db.recetas.find_one({"_id": "RC004"})
                self.assertEqual(receta["dispensas_realizadas"], hechas + exitos)
                self.assertEqual(receta["estado"], "Completada" if hechas + exitos == 3 else "Vigente")
                self.assertEqual(self.db.stock_lotes.find_one({"_id": "L014"})["unidades"], 0)
                self.assertEqual(self.db.stock_lotes.find_one({"_id": "LX001"})["unidades"], unidades - exitos)
                self.assertEqual(self.db.stock_lotes.find_one({"_id": "LX000"})["unidades"], 100)
                self.assertEqual(self.db.stock_lotes.count_documents({"unidades": {"$lt": 0}}), 0)
