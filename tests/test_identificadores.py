"""Q13 y Q14 generan identificadores únicos incluso con llamadas concurrentes."""

import io
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
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
from consultas import q11, q13, q14, q15


class IdentificadoresMongo(unittest.TestCase):
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
        for modulo in (cargar, q11, q13, q14, q15, reglas):
            self.enterContext(patch.object(modulo, "base", return_value=self.db))
        for modulo in (q14, q15, reglas):
            self.enterContext(patch.object(modulo, "hoy", return_value=datetime(2026, 11, 14)))
        for modulo in (q13, q14):
            self.enterContext(patch.object(modulo, "proyectar", return_value=None))
        self.cargar()

    def cargar(self):
        with redirect_stdout(io.StringIO()):
            cargar._escribir(self.tablas)

    def cliente_nuevo(self, numero):
        return q13.ejecutar("alta", nombre="Ana", apellido="Prueba", dni=f"9900{numero:04d}",
                            email="ana@example.test", telefono="123", ciudad="CABA",
                            provincia="Buenos Aires", obra_social="Sin cobertura")

    def preparar_sucursales(self, cantidad):
        sucursal = self.db.sucursales.find_one({"_id": "S001"})
        farmaceutico = self.db.farmaceuticos.find_one({"_id": "F001"})
        lote = self.db.stock_lotes.find_one({"_id": "L001"})
        for i in range(cantidad):
            self.db.sucursales.insert_one({**sucursal, "_id": f"SX{i}", "id_sucursal": f"SX{i}"})
            self.db.farmaceuticos.insert_one({**farmaceutico, "_id": f"FX{i}", "id_farmaceutico": f"FX{i}",
                                              "id_sucursal": f"SX{i}", "matricula": f"MX{i}"})
            self.db.stock_lotes.insert_one({**lote, "_id": f"LX{i}", "id_lote": f"LX{i}",
                                            "id_sucursal": f"SX{i}"})

    def venta_nueva(self, numero):
        return q14.ejecutar("C001", f"FX{numero}",
                            [{"id_producto": "PRD001", "cantidad": 1},
                             {"id_producto": "PRD001", "cantidad": 1}], "Efectivo")

    def comprobar_ventas_concurrentes(self, cantidad):
        with ThreadPoolExecutor(max_workers=cantidad) as pool:
            respuestas = list(pool.map(self.venta_nueva, range(cantidad)))
        self.assertTrue(all(r["ok"] for r in respuestas), respuestas)
        ventas = [r["documento"] for r in respuestas]
        self.assertEqual(len({v["_id"] for v in ventas}), cantidad)
        ids = [i["id_detalle"] for v in ventas for i in v["items"]]
        self.assertEqual(len(set(ids)), cantidad * 2)
        self.assertEqual(set(ids), {f"D{i:03d}" for i in range(23, 23 + cantidad * 2)})

    def test_ventas_concurrentes_reservan_detalles_y_ventas_distintos(self):
        self.preparar_sucursales(6)
        self.comprobar_ventas_concurrentes(6)

    def test_clientes_concurrentes_e_indice_dni(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            respuestas = list(pool.map(self.cliente_nuevo, range(8)))
        self.assertTrue(all(r["ok"] for r in respuestas), respuestas)
        self.assertEqual({r["documento"]["_id"] for r in respuestas}, {f"C{i:03d}" for i in range(9, 17)})
        with ThreadPoolExecutor(max_workers=4) as pool:
            respuestas = list(pool.map(self.cliente_nuevo, [99] * 4))
        self.assertEqual(sum(r["ok"] for r in respuestas), 1, respuestas)
        self.assertEqual(self.db.clientes.count_documents({"dni": "99000099"}), 1)
