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
        for modulo in (cargar, q01, q05, q07, q08, q09, q15, reglas):
            self.enterContext(patch.object(modulo, "base", return_value=self.db))
        for modulo in (q05, q15):
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

    def test_q08_dataset_y_referencias(self):
        resultado = q08.ejecutar()
        self.assertEqual([l["_id"] for l in resultado],
                         ["L002", "L003", "L005", "L007", "L010", "L011", "L012", "L014", "L018"])
        for lote in resultado:
            self.assertEqual(lote["producto"]["_id"], lote["id_producto"])
            self.assertEqual(lote["sucursal"]["_id"], lote["id_sucursal"])
            self.assertEqual(lote["proveedor"]["_id"], lote["producto"]["id_proveedor"])

    def test_q08_limite_cero_drogueria_y_vencidos(self):
        for identificador, unidades in (("L001", 50), ("L004", 0), ("L016", 49)):
            self.db.stock_lotes.update_one({"_id": identificador}, {"$set": {"unidades": unidades}})
        resultado = {l["_id"]: l for l in q08.ejecutar()}
        self.assertNotIn("L001", resultado)
        self.assertEqual(resultado["L004"]["unidades"], 0)
        self.assertEqual(resultado["L016"]["sucursal"]["tipo"], "Droguería")
        self.assertLess(resultado["L018"]["vencimiento"], HOY)
        self.assertFalse(resultado["L018"]["producto"]["activo"])

    def test_q07_dataset(self):
        self.assertEqual([(p["id_producto"], p["unidades_vendidas"]) for p in q07.ejecutar()],
                         [("PRD005", 6), ("PRD011", 5), ("PRD001", 4), ("PRD004", 3), ("PRD009", 2)])

    def test_q07_empate_lineas_repetidas_y_estados(self):
        self.db.ventas.delete_many({})
        items = [{"id_detalle": f"DX{i}", "id_producto": f"PRD{i:03d}",
                  "cantidad": 2, "precio_unit": 100} for i in range(2, 7)]
        items.extend([
            {"id_detalle": "DX7", "id_producto": "PRD001", "cantidad": 1, "precio_unit": 100},
            {"id_detalle": "DX8", "id_producto": "PRD001", "cantidad": 1, "precio_unit": 100},
        ])
        self.venta("VX01", items=items)
        for estado in ("Pendiente", "Anulada"):
            self.venta(f"VX_{estado}", estado=estado, items=[
                {"id_detalle": f"DX_{estado}", "id_producto": "PRD006", "cantidad": 1000, "precio_unit": 1}])
        self.assertEqual([(p["id_producto"], p["unidades_vendidas"]) for p in q07.ejecutar()],
                         [(f"PRD{i:03d}", 2) for i in range(1, 6)])

    def test_q07_vacio_y_producto_inactivo(self):
        self.db.ventas.delete_many({})
        self.assertEqual(q07.ejecutar(), [])
        self.venta("VX01", items=[
            {"id_detalle": "DX1", "id_producto": "PRD012", "cantidad": 3, "precio_unit": 1800}])
        self.assertEqual(q07.ejecutar(), [{
            "id_producto": "PRD012", "nombre": "Alcohol en gel 250ml", "unidades_vendidas": 3}])

    def test_q05_dataset(self):
        self.assertEqual({f["id_farmaceutico"]: f["cantidad_ventas"] for f in q05.ejecutar()},
                         {"F001": 1, "F002": 2, "F003": 1, "F005": 3, "F006": 1, "F007": 0})

    def test_q05_fechas_estados_ceros_y_conteo_de_ventas(self):
        self.db.ventas.delete_many({})
        self.venta("VX01", fecha=HOY - timedelta(days=60))
        self.venta("VX02", fecha=HOY - timedelta(days=61))
        self.venta("VX03", fecha=HOY + timedelta(hours=23, minutes=59))
        self.venta("VX04", fecha=HOY + timedelta(days=1))
        self.venta("VX05", estado="Anulada")
        self.venta("VX06", estado="Pendiente", items=[
            {"id_detalle": "DX1", "id_producto": "PRD001", "cantidad": 2, "precio_unit": 10},
            {"id_detalle": "DX2", "id_producto": "PRD002", "cantidad": 3, "precio_unit": 10}])
        self.venta("VX07", id_farmaceutico="F004")
        self.assertEqual({f["id_farmaceutico"]: f["cantidad_ventas"] for f in q05.ejecutar()},
                         {"F001": 3, "F002": 0, "F003": 0, "F005": 0, "F006": 0, "F007": 0})







if __name__ == "__main__":
    unittest.main(verbosity=2)
