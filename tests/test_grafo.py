"""Integración: FARMARED_TEST_NEO4J_URI debe apuntar a un grafo descartable.

La reconstrucción vacía ese grafo. Mongo usa una base temporal propia.
"""

import io
import os
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
import grafo
import reglas
from consultas import q02, q03, q10, q11, q13, q14, q15


@unittest.skipUnless(os.environ.get("FARMARED_TEST_NEO4J_URI"),
                     "requiere un Neo4j descartable en FARMARED_TEST_NEO4J_URI")
class ConsultasGrafo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cliente = db.cliente()
        cls.addClassCleanup(cls.cliente.close)
        cls.cliente.admin.command("ping")
        cls.db = cls.cliente[f"farmared_test_{uuid4().hex}"]
        cls.addClassCleanup(cls.cliente.drop_database, cls.db.name)

    def setUp(self):
        self.enterContext(patch.object(grafo, "NEO4J_URI", os.environ["FARMARED_TEST_NEO4J_URI"]))
        for modulo in (cargar, grafo, q11, q13, q14, q15, reglas):
            self.enterContext(patch.object(modulo, "base", return_value=self.db))
        for modulo in (q14, q15, reglas):
            self.enterContext(patch.object(modulo, "hoy", return_value=datetime(2026, 11, 14)))
        tablas = {nombre: {"catedra": cargar._leer(cargar.DATOS / nombre, nombre, True),
                           "propios": []} for nombre in cargar.ARCHIVOS}
        cargar._validar(tablas)
        with redirect_stdout(io.StringIO()):
            cargar._escribir(tablas)
        grafo.reconstruir()

    def test_carga_idempotente_y_consultas(self):
        for _ in range(2):
            self.assertEqual(grafo.consultar("MATCH (n) RETURN count(n) AS n"), [{"n": 58}])
            self.assertEqual(grafo.consultar("MATCH ()-[r]->() RETURN count(r) AS n"), [{"n": 96}])
            self.assertEqual([v["id_venta"] for v in q02.ejecutar()], ["V012", "V011"])
            self.assertEqual([e["id"] for e in q03.ejecutar("C006")],
                             ["RC003", "V006", "V007", "RC004", "V008", "V016"])
            self.assertEqual(q03.ejecutar("C999"), [])
            self.assertEqual(q03.ejecutar("C008"), [])
            self.assertEqual([c["id_cliente"] for c in q10.ejecutar("S002")], ["C001", "C004"])
            self.assertEqual(q10.ejecutar("S005"), [])
            grafo.reconstruir()

    def test_sucursal_historica_y_actualizacion_de_relaciones(self):
        self.db.farmaceuticos.update_one({"_id": "F004"}, {"$set": {"id_sucursal": "S001"}})
        grafo.reconstruir()
        self.assertIn("C004", [c["id_cliente"] for c in q10.ejecutar("S002")])
        self.assertNotIn("C004", [c["id_cliente"] for c in q10.ejecutar("S001")])
        venta = self.db.ventas.find_one({"_id": "V013"})
        venta["id_cliente"] = "C008"
        venta["items"] = [{"id_detalle": "DX1", "id_producto": "PRD001", "cantidad": 1, "precio_unit": 100},
                          {"id_detalle": "DX2", "id_producto": "PRD001", "cantidad": 2, "precio_unit": 200}]
        for _ in range(2):
            grafo.upsert_venta(venta)
        self.assertEqual(grafo.consultar(
            "MATCH (c:Cliente)-[:REALIZO]->(:Venta {id: 'V013'}) RETURN c.id AS id"), [{"id": "C008"}])
        self.assertEqual(grafo.consultar(
            "MATCH (:Venta {id: 'V013'})-[r:INCLUYE]->() RETURN r.precio_unit AS precio ORDER BY precio"),
            [{"precio": 100}, {"precio": 200}])
        venta["items"][0]["id_producto"] = "inexistente"
        with self.assertRaises(grafo.ReferenciaGrafo):
            grafo.upsert_venta(venta)
        self.assertEqual(len(grafo.consultar("MATCH (:Venta {id: 'V013'})-[r:INCLUYE]->() RETURN r")), 2)

    def test_escrituras_proyectadas_y_rechazo_sin_cambios(self):
        respuesta = q13.ejecutar("modificar", id_cliente="C001", telefono="123456")
        self.assertTrue(respuesta["ok"], respuesta)
        self.assertNotIn("aviso_grafo", respuesta)
        self.assertEqual(grafo.consultar("MATCH (c:Cliente {id: 'C001'}) RETURN c.telefono AS t"), [{"t": "123456"}])
        respuesta = q14.ejecutar("C006", "F001", [{"id_producto": "PRD003", "cantidad": 50}], "Obra social", "RC003")
        self.assertTrue(respuesta["ok"], respuesta)
        self.assertNotIn("aviso_grafo", respuesta)
        self.assertEqual(respuesta["documento"]["items"][0]["lotes"],
                         [{"id_lote": "L005", "unidades": 40}, {"id_lote": "L015", "unidades": 10}])
        self.assertEqual(grafo.consultar("MATCH (r:Receta {id: 'RC003'}) RETURN r.estado AS estado"), [{"estado": "Completada"}])
        respuesta = q15.ejecutar("V011")
        self.assertTrue(respuesta["ok"], respuesta)
        self.assertNotIn("aviso_grafo", respuesta)
        self.assertEqual([v["id_venta"] for v in q02.ejecutar()], ["V012"])
        antes = {nombre: list(self.db[nombre].find()) for nombre in ("ventas", "recetas", "stock_lotes")}
        respuesta = q14.ejecutar("C001", "F001", [{"id_producto": "PRD001", "cantidad": 100000}], "Efectivo")
        self.assertFalse(respuesta["ok"], respuesta)
        self.assertEqual(antes, {nombre: list(self.db[nombre].find()) for nombre in antes})
