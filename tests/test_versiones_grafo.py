"""Q10 refleja la baja de Q13 aunque otra modificación se proyecte tarde."""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

RAIZ = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RAIZ / "src"), str(RAIZ / "scripts")]

import cargar
import db
import grafo
from consultas import q10, q11, q13


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
        for modulo in (cargar, grafo, q11, q13):
            self.enterContext(patch.object(modulo, "base", return_value=self.db))
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
            return grafo.proyectar(funcion, documento)

        with patch.object(q13, "proyectar", demorar):
            cambio = q13.ejecutar("modificar", id_cliente="C001", telefono="111")
        self.assertTrue(cambio["ok"], cambio)
        self.assertFalse(self.db.clientes.find_one({"_id": "C001"})["activo"])
        cliente = next(c for c in q10.ejecutar("S002") if c["id_cliente"] == "C001")
        self.assertFalse(cliente["activo"])
