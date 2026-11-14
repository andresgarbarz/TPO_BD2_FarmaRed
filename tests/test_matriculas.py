"""La matrícula es única tanto en los CSV como en MongoDB. [P18, p. 2]"""

import copy
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

RAIZ = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RAIZ / "src"), str(RAIZ / "scripts")]

import cargar
import db
from consultas import q11


class MatriculasUnicas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cliente = db.cliente()
        cls.addClassCleanup(cls.cliente.close)
        cls.cliente.admin.command("ping")
        cls.db = cls.cliente[f"farmared_test_matriculas_{uuid4().hex}"]
        cls.addClassCleanup(cls.cliente.drop_database, cls.db.name)
        cls.tablas = {
            nombre: {"catedra": cargar._leer(cargar.DATOS / nombre, nombre, True), "propios": []}
            for nombre in cargar.ARCHIVOS
        }

    def setUp(self):
        self.enterContext(patch.object(cargar, "base", return_value=self.db))
        self.enterContext(patch.object(q11, "base", return_value=self.db))
        self.cargar()

    def cargar(self):
        with redirect_stdout(io.StringIO()):
            cargar._escribir(self.tablas)

    def test_rechaza_matriculas_repetidas_antes_de_borrar(self):
        self.db.clientes.insert_one({"_id": "preservar", "dni": "no-borrar"})
        antes = {nombre: list(self.db[nombre].find()) for nombre in db.COLECCIONES}
        for origen in ("catedra", "propios"):
            with self.subTest(origen=origen):
                tablas = copy.deepcopy(self.tablas)
                repetido = {**tablas["farmaceuticos.csv"]["catedra"][0], "id_farmaceutico": "F008"}
                tablas["farmaceuticos.csv"][origen].append(repetido)
                with self.assertRaisesRegex(cargar.CargaInvalida, "matrícula.*repetida"):
                    cargar._escribir(tablas)
                self.assertEqual(antes, {nombre: list(self.db[nombre].find()) for nombre in db.COLECCIONES})

    def test_indice_unico_sobrevive_a_recargas(self):
        for _ in range(2):
            self.cargar()
            indice = self.db.farmaceuticos.index_information()["matricula_unica"]
            self.assertEqual(indice["key"], [("matricula", 1)])
            self.assertTrue(indice["unique"])
            repetido = self.db.farmaceuticos.find_one({"_id": "F001"})
            repetido.update({"_id": "F008", "id_farmaceutico": "F008"})
            with self.assertRaises(DuplicateKeyError):
                self.db.farmaceuticos.insert_one(repetido)
            self.assertEqual(self.db.farmaceuticos.count_documents({}), 7)
