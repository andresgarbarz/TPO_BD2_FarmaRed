"""Integración contra MongoDB real; solo usa y elimina una base temporal propia."""

import io
import sys
import unittest
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
from consultas import q01, q05, q07, q08, q09, q11, q15

HOY = datetime(2026, 11, 10)


class ConsultasMongo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cliente = db.cliente()
        cls.addClassCleanup(cls.cliente.close)
        cls.cliente.admin.command("ping")
        cls.db = cls.cliente[f"farmared_test_{uuid4().hex}"]
        cls.addClassCleanup(cls.cliente.drop_database, cls.db.name)
        cls.tablas = {
            nombre: {"catedra": cargar._leer(cargar.DATOS / nombre, nombre, True),
                     "propios": []}
            for nombre in cargar.ARCHIVOS
        }
        cargar._validar(cls.tablas)

    def setUp(self):
        for modulo in (cargar, q01, q09, q15, reglas):
            self.enterContext(patch.object(modulo, "base", return_value=self.db))
        for modulo in (q15,):
            self.enterContext(patch.object(modulo, "hoy", return_value=HOY))
        self.cargar()

    def cargar(self):
        with redirect_stdout(io.StringIO()):
            cargar._escribir(self.tablas)

    def venta(self, identificador, fecha=HOY, estado="Completada", total=100,
              id_farmaceutico="F001", tipo="Venta libre", items=None):
        if items is None:
            items = [{"id_detalle": f"D_{identificador}", "id_producto": "PRD001",
                      "cantidad": 1, "precio_unit": total}]
        self.db.ventas.insert_one({
            "_id": identificador, "id_venta": identificador, "id_cliente": "C001",
            "id_farmaceutico": id_farmaceutico,
            "id_receta": "RC001" if tipo == "Con receta" else None,
            "fecha": fecha, "tipo": tipo, "medio_pago": "Efectivo",
            "total": sum(i["cantidad"] * i["precio_unit"] for i in items),
            "estado": estado, "items": items,
        })

    def test_q09_dataset(self):
        self.assertEqual([v["_id"] for v in q09.ejecutar()], ["V013", "V014"])

    def test_q09_limite_y_estados(self):
        self.venta("VX01", total=4999, estado="Pendiente")
        self.venta("VX02", total=5000)
        self.venta("VX03", total=100, estado="Anulada")
        self.venta("VX04", total=4999, tipo="Con receta")
        resultado = q09.ejecutar()
        self.assertEqual([v["_id"] for v in resultado], ["V013", "V014", "VX01"])
        self.assertEqual(resultado[-1]["items"][0]["precio_unit"], 4999)

    def test_q01_dataset_y_proveedor_completo(self):
        resultado = q01.ejecutar()
        self.assertEqual([p["_id"] for p in resultado],
                         [f"PRD{i:03d}" for i in range(1, 12)])
        for producto in resultado:
            self.assertEqual(producto["proveedor"], self.db.proveedores.find_one(
                {"_id": producto["id_proveedor"]}))

    def test_q01_proveedor_inactivo_y_producto_inactivo(self):
        self.db.productos.update_one({"_id": "PRD001"}, {"$set": {"id_proveedor": "PRV005"}})
        self.db.productos.update_one({"_id": "PRD002"}, {"$set": {"activo": False}})
        resultado = q01.ejecutar()
        self.assertEqual(len(resultado), 10)
        self.assertEqual(len({p["_id"] for p in resultado}), 10)
        self.assertEqual(resultado[0]["_id"], "PRD001")
        self.assertFalse(resultado[0]["proveedor"]["activo"])
        self.assertNotIn("PRD002", [p["_id"] for p in resultado])














if __name__ == "__main__":
    unittest.main(verbosity=2)
