"""Q02 refleja la venta completada por Q15 tras recuperar Neo4j."""

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

from neo4j.exceptions import ServiceUnavailable

import cargar
import db
import grafo
import reglas
from consultas import q02, q11, q15


@unittest.skipUnless(os.environ.get("FARMARED_TEST_NEO4J_URI"),
                     "requiere un Neo4j descartable en FARMARED_TEST_NEO4J_URI")
class RecuperacionGrafo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cliente = db.cliente()
        cls.addClassCleanup(cls.cliente.close)
        cls.cliente.admin.command("ping")
        cls.db = cls.cliente[f"farmared_test_{uuid4().hex}"]
        cls.addClassCleanup(cls.cliente.drop_database, cls.db.name)

    def setUp(self):
        self.enterContext(patch.object(grafo, "NEO4J_URI", os.environ["FARMARED_TEST_NEO4J_URI"]))
        for modulo in (cargar, grafo, q11, q15, reglas):
            self.enterContext(patch.object(modulo, "base", return_value=self.db))
        for modulo in (q15, reglas):
            self.enterContext(patch.object(modulo, "hoy", return_value=datetime(2026, 11, 14)))
        self.tablas = {nombre: {"catedra": cargar._leer(cargar.DATOS / nombre, nombre, True),
                               "propios": []} for nombre in cargar.ARCHIVOS}
        with redirect_stdout(io.StringIO()):
            cargar._escribir(self.tablas)
        grafo.reconstruir()

    def test_venta_confirmada_con_neo4j_caido_se_recupera_antes_de_leer(self):
        with patch.object(grafo, "_sesion", side_effect=ServiceUnavailable("caído")):
            respuesta = q15.ejecutar("V011")
            self.assertTrue(respuesta["ok"], respuesta)
            self.assertIn("aviso_grafo", respuesta)
            with self.assertRaises(grafo.GrafoPendiente):
                q02.ejecutar()
        self.assertEqual([v["id_venta"] for v in q02.ejecutar()], ["V012"])
        self.assertEqual(self.db.stock_lotes.find_one({"_id": "L014"})["unidades"], 44)
        self.assertEqual(self.db.recetas.find_one({"_id": "RC006"})["estado"], "Completada")
