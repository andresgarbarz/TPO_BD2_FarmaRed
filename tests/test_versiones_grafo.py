"""Las proyecciones viejas no pueden reemplazar datos más nuevos de Neo4j."""

import copy
import io
import os
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

RAIZ = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RAIZ / "src"), str(RAIZ / "scripts")]

import cargar
import db
import grafo
import reglas
from consultas import q10, q11, q13, q14, q15


@unittest.skipUnless(os.environ.get("FARMARED_TEST_NEO4J_URI"),
                     "requiere un Neo4j descartable en FARMARED_TEST_NEO4J_URI")
class VersionesGrafo(unittest.TestCase):
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
        with redirect_stdout(io.StringIO()):
            cargar._escribir(tablas)
        grafo.reconstruir()

    def test_baja_no_se_revierte_por_modificacion_proyectada_tarde(self):
        def demorar(funcion, documento):
            with patch.object(q13, "proyectar", grafo.proyectar):
                baja = q13.ejecutar("baja", id_cliente="C001")
            self.assertTrue(baja["ok"], baja)
            self.assertEqual(baja["documento"]["_version"], 2)
            return grafo.proyectar(funcion, documento)

        with patch.object(q13, "proyectar", demorar):
            cambio = q13.ejecutar("modificar", id_cliente="C001", telefono="111")
        self.assertTrue(cambio["ok"], cambio)
        self.assertEqual(cambio["documento"]["_version"], 1)
        self.assertFalse(self.db.clientes.find_one({"_id": "C001"})["activo"])
        cliente = next(c for c in q10.ejecutar("S002") if c["id_cliente"] == "C001")
        self.assertFalse(cliente["activo"])
        self.assertEqual(grafo.consultar(
            "MATCH (c:Cliente {id: 'C001'}) RETURN c._version AS version"), [{"version": 2}])

    def test_venta_y_receta_viejas_no_reemplazan_propiedades_ni_relaciones(self):
        venta = self.db.ventas.find_one({"_id": "V011"})
        receta = self.db.recetas.find_one({"_id": "RC006"})
        vieja = copy.deepcopy(venta)
        vieja.update({"_version": 1, "id_cliente": "C008", "id_sucursal": "S001"})
        receta_vieja = copy.deepcopy(receta)
        receta_vieja["_version"] = 1
        venta.update({"_version": 2, "estado": "Completada"})
        receta.update({"_version": 2, "estado": "Completada", "dispensas_realizadas": 1})
        grafo.upsert_venta_y_receta(venta, receta)
        grafo.upsert_venta_y_receta(vieja, receta_vieja)
        self.assertEqual(grafo.consultar(
            "MATCH (c:Cliente)-[:REALIZO]->(v:Venta {id: 'V011'})-[:EN_SUCURSAL]->(s) "
            "RETURN v.estado AS estado, v._version AS version, c.id AS cliente, s.id AS sucursal"),
            [{"estado": "Completada", "version": 2, "cliente": "C007", "sucursal": "S004"}])
        self.assertEqual(grafo.consultar(
            "MATCH (r:Receta {id: 'RC006'}) RETURN r.estado AS estado, "
            "r.dispensas_realizadas AS dispensas, r._version AS version"),
            [{"estado": "Completada", "dispensas": 1, "version": 2}])

    def test_proyecciones_concurrentes_conservan_la_version_mayor(self):
        cliente = self.db.clientes.find_one({"_id": "C001"})
        for version in range(1, 11, 2):
            barrera = Barrier(2)
            def proyectar(numero):
                documento = {**cliente, "_version": numero, "activo": numero % 2 == 1}
                barrera.wait(timeout=10)
                grafo.upsert_cliente(documento)
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(proyectar, (version, version + 1)))
            self.assertEqual(grafo.consultar(
                "MATCH (c:Cliente {id: 'C001'}) RETURN c._version AS version, c.activo AS activo"),
                [{"version": version + 1, "activo": False}])

    def test_escrituras_incrementan_version_de_los_documentos(self):
        alta = q13.ejecutar("alta", nombre="Ana", apellido="Prueba", dni="99900011",
                            email="ana@example.test", telefono="123", ciudad="CABA",
                            provincia="Buenos Aires", obra_social="Sin cobertura")
        self.assertTrue(alta["ok"], alta)
        self.assertEqual(alta["documento"]["_version"], 1)
        venta = q14.ejecutar("C006", "F001", [{"id_producto": "PRD003", "cantidad": 1}],
                            "Efectivo", "RC003")
        self.assertTrue(venta["ok"], venta)
        self.assertEqual(venta["documento"]["_version"], 1)
        self.assertEqual(self.db.recetas.find_one({"_id": "RC003"})["_version"], 1)
        venta = q15.ejecutar("V011")
        self.assertTrue(venta["ok"], venta)
        self.assertEqual(venta["documento"]["_version"], 1)
        self.assertEqual(self.db.recetas.find_one({"_id": "RC006"})["_version"], 1)
