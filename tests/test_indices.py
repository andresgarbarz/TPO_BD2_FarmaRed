"""Planes reales: las lecturas no deben recorrer ventas ajenas al período."""

import io
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from pymongo.collection import Collection

RAIZ = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RAIZ / "src"), str(RAIZ / "scripts")]

import cargar
import db
from consultas import q05, q11, q12


class IndicesMongo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cliente = db.cliente()
        cls.addClassCleanup(cls.cliente.close)
        cls.cliente.admin.command("ping")
        cls.db = cls.cliente[f"farmared_test_{uuid4().hex}"]
        cls.addClassCleanup(cls.cliente.drop_database, cls.db.name)

    def setUp(self):
        for modulo in (cargar, q05, q11, q12):
            self.enterContext(patch.object(modulo, "base", return_value=self.db))
        for modulo in (q05, q11, q12):
            self.enterContext(patch.object(modulo, "hoy", return_value=datetime(2026, 11, 14)))
        tablas = {nombre: {"catedra": cargar._leer(cargar.DATOS / nombre, nombre, True),
                           "propios": []} for nombre in cargar.ARCHIVOS}
        with redirect_stdout(io.StringIO()):
            cargar._escribir(tablas)
        venta = self.db.ventas.find_one({"_id": "V013"})
        self.db.ventas.insert_many([
            {**venta, "_id": f"VX{i:05d}", "id_venta": f"VX{i:05d}", "fecha": datetime(2020, 1, 1)}
            for i in range(20000)
        ])

    def explicar(self, modulo, coleccion):
        pipelines = []
        with patch.object(Collection, "aggregate", lambda col, pipeline: pipelines.append(pipeline) or []):
            modulo.ejecutar()
        return self.db.command("explain", {"aggregate": coleccion,
                               "pipeline": pipelines[0], "cursor": {}}, verbosity="executionStats")

    def test_q05_q12_usan_indices_en_lookup(self):
        for modulo, coleccion, indice in (
            (q05, "farmaceuticos", "ventas_farmaceutico_fecha"),
            (q12, "clientes", "ventas_cliente_fecha"),
        ):
            with self.subTest(consulta=modulo.ID):
                resultado = modulo.ejecutar()
                self.db.ventas.drop_indexes()
                antes = next(s for s in self.explicar(modulo, coleccion)["stages"] if "$lookup" in s)
                cargar.crear_indices()
                despues = next(s for s in self.explicar(modulo, coleccion)["stages"] if "$lookup" in s)
                self.assertGreater(antes["collectionScans"], 0)
                self.assertGreater(antes["totalDocsExamined"], 20000)
                self.assertIn(indice, despues["indexesUsed"])
                self.assertEqual(despues["collectionScans"], 0)
                self.assertLess(despues["totalDocsExamined"], 20)
                self.assertEqual(modulo.ejecutar(), resultado)

    def test_q11_filtra_antes_de_agrupar_y_no_recorre_historial(self):
        venta = self.db.ventas.find_one({"_id": "V013"})
        self.db.ventas.insert_many([
            {**venta, "_id": "VXN1", "id_venta": "VXN1", "fecha": datetime(2026, 11, 1), "total": 300},
            {**venta, "_id": "VXN2", "id_venta": "VXN2", "fecha": datetime(2026, 11, 30),
             "id_farmaceutico": "F004", "total": 500},
        ])
        for fecha, esperados, documentos in (
            (datetime(2026, 11, 14), {"F001": 300, "F004": 500}, 2),
            (datetime(2026, 12, 14), {}, 0),
        ):
            with self.subTest(fecha=fecha), patch.object(q11, "hoy", return_value=fecha):
                resultado = q11.ejecutar()
                self.assertEqual({f["id_farmaceutico"]: f["ingresos_totales"] for f in resultado}, esperados)
                self.assertTrue(all((f["anio"], f["mes"]) == (fecha.year, fecha.month) for f in resultado))
                cursor = next(s["$cursor"] for s in self.explicar(q11, q11.VISTA)["stages"] if "$cursor" in s)
                self.assertEqual(cursor["executionStats"]["totalDocsExamined"], documentos)
                self.assertIn("ventas_estado_fecha", str(cursor["queryPlanner"]["winningPlan"]))

    def test_fefo_usa_el_indice_para_filtrar_y_ordenar(self):
        lotes = self.db.stock_lotes
        lote = lotes.find_one({"_id": "L005"})
        lotes.insert_many([{**lote, "_id": f"LX{i:05d}", "id_producto": "PRD001", "id_sucursal": "S002"}
                           for i in range(1000)])
        plan = lotes.find({"id_producto": "PRD003", "id_sucursal": "S001",
                           "vencimiento": {"$gte": datetime(2026, 11, 14)}}).sort([
                               ("vencimiento", 1), ("_id", 1)]).explain()
        self.assertIn("lotes_fefo", str(plan["queryPlanner"]["winningPlan"]))
        self.assertNotIn("'stage': 'SORT'", str(plan["queryPlanner"]["winningPlan"]))
        self.assertEqual(plan["executionStats"]["totalDocsExamined"], 2)
