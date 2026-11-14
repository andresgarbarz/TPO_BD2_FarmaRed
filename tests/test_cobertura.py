"""La cobertura se valida sobre el mismo estado que se actualiza."""

import io
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

RAIZ = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RAIZ / "src"), str(RAIZ / "scripts")]

import cargar
import db
from consultas import q11, q13
from pymongo.collection import Collection


class CoberturaConcurrente(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cliente = db.cliente()
        cls.addClassCleanup(cls.cliente.close)
        cls.cliente.admin.command("ping")
        cls.db = cls.cliente[f"farmared_test_{uuid4().hex}"]
        cls.addClassCleanup(cls.cliente.drop_database, cls.db.name)

    def setUp(self):
        for modulo in (cargar, q11, q13):
            self.enterContext(patch.object(modulo, "base", return_value=self.db))
        self.enterContext(patch.object(q13, "proyectar", return_value=None))
        tablas = {nombre: {"catedra": cargar._leer(cargar.DATOS / nombre, nombre, True),
                           "propios": []} for nombre in cargar.ARCHIVOS}
        with redirect_stdout(io.StringIO()):
            cargar._escribir(tablas)

    def test_cambios_concurrentes_no_mezclan_cobertura_y_afiliado(self):
        self.db.clientes.update_one({"_id": "C001"}, {"$set": {
            "obra_social": "OSDE", "nro_afiliado": "11", "_version": 0}})
        barrera = Barrier(2)
        leer = Collection.find_one

        def leer_antes_de_cambiar(coleccion, filtro, *args, **kwargs):
            documento = leer(coleccion, filtro, *args, **kwargs)
            if (coleccion.database.name == self.db.name and coleccion.name == "clientes"
                    and filtro == {"_id": "C001"}):
                barrera.wait(timeout=10)
            return documento

        cambios = [{"nro_afiliado": "55"},
                   {"obra_social": "Sin cobertura", "nro_afiliado": None}]
        with patch.object(Collection, "find_one", leer_antes_de_cambiar):
            with ThreadPoolExecutor(max_workers=2) as pool:
                respuestas = list(pool.map(
                    lambda datos: q13.ejecutar("modificar", id_cliente="C001", **datos), cambios))
        self.assertEqual(sum(r["ok"] for r in respuestas), 1, respuestas)
        rechazo = next(r for r in respuestas if not r["ok"])
        self.assertIn("reintentá", rechazo["error"])
        cliente = self.db.clientes.find_one({"_id": "C001"})
        self.assertIn((cliente["obra_social"], cliente["nro_afiliado"]),
                      (("OSDE", "55"), ("Sin cobertura", None)))
        self.assertEqual(cliente["_version"], 1)

    def test_contacto_y_cobertura_conservan_snapshot_y_version(self):
        antes = self.db.clientes.find_one({"_id": "C001"})
        respuesta = q13.ejecutar("modificar", id_cliente="C001", telefono="999")
        self.assertTrue(respuesta["ok"], respuesta)
        self.assertEqual(respuesta["documento"]["telefono"], "999")
        self.assertEqual(respuesta["documento"]["_version"], 1)
        self.assertEqual(respuesta["documento"]["obra_social"], antes["obra_social"])
        respuesta = q13.ejecutar("modificar", id_cliente="C001",
                                 obra_social="Sin cobertura", nro_afiliado=None)
        self.assertTrue(respuesta["ok"], respuesta)
        self.assertEqual(respuesta["documento"]["_version"], 2)
        self.assertIsNone(respuesta["documento"]["nro_afiliado"])
