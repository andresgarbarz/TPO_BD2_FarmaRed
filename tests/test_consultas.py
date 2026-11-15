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
from consultas import q01, q04, q05, q06, q07, q08, q09, q11, q12, q15

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
        for modulo in (cargar, q01, q04, q05, q06, q07, q08, q09, q11, q12, q15, reglas):
            self.enterContext(patch.object(modulo, "base", return_value=self.db))
        for modulo in (q05, q06, q11, q12, q15):
            self.enterContext(patch.object(modulo, "hoy", return_value=HOY))
        self.enterContext(patch.object(q15, "proyectar", return_value=None))
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

    def test_q04_todas_las_recetas_y_clientes_inactivos(self):
        self.assertEqual([(c["id_cliente"], c["cantidad_recetas"]) for c in q04.ejecutar()],
                         [("C001", 2), ("C002", 2), ("C006", 2)])
        self.db.clientes.update_one({"_id": "C001"}, {"$set": {"activo": False}})
        self.db.recetas.update_many({"id_cliente": "C001"}, {"$set": {"estado": "Vencida"}})
        self.assertEqual(q04.ejecutar()[0]["cantidad_recetas"], 2)

    def test_q06_dataset_y_cliente_completo(self):
        resultado = q06.ejecutar()
        self.assertEqual([r["_id"] for r in resultado], ["RC002", "RC003", "RC004"])
        for receta in resultado:
            self.assertEqual(receta["cliente"], self.db.clientes.find_one(
                {"_id": receta["id_cliente"]}))

    def test_q06_limites_nulos_estados_y_cliente_inactivo(self):
        self.db.recetas.delete_many({})
        self.db.clientes.update_one({"_id": "C001"}, {"$set": {"activo": False}})
        for i, fecha in enumerate((HOY - timedelta(days=1), HOY, HOY + timedelta(days=1), None)):
            self.db.recetas.insert_one({"_id": f"RX{i}", "id_cliente": "C001",
                "tipo": "Tratamiento prolongado", "estado": "Vigente", "proxima_dispensa": fecha})
        self.db.recetas.insert_one({"_id": "RX4", "id_cliente": "C001",
            "tipo": "Tratamiento prolongado", "estado": "Vigente"})
        for i, cambios in enumerate(({"estado": "Vencida"}, {"tipo": "Simple"}), 5):
            self.db.recetas.insert_one({"_id": f"RX{i}", "id_cliente": "C001",
                "tipo": "Tratamiento prolongado", "estado": "Vigente",
                "proxima_dispensa": HOY - timedelta(days=1), **cambios})
        self.assertEqual([r["_id"] for r in q06.ejecutar()], ["RX0"])
        self.assertFalse(q06.ejecutar()[0]["cliente"]["activo"])

    def test_q12_dataset(self):
        self.assertEqual([c["_id"] for c in q12.ejecutar()], ["C004", "C008"])

    def test_q12_ventana_estados_y_clientes_sin_compras(self):
        self.db.ventas.delete_many({})
        for dias in (365, -1):
            self.venta(f"VX{dias}", fecha=HOY - timedelta(days=dias))
        self.assertIn("C001", [c["_id"] for c in q12.ejecutar()])
        self.db.clientes.update_one({"_id": "C001"}, {"$set": {"activo": False}})
        for estado in ("Completada", "Pendiente", "Anulada"):
            with self.subTest(estado=estado):
                self.venta("VXreciente", fecha=HOY - timedelta(days=364), estado=estado)
                self.assertNotIn("C001", [c["_id"] for c in q12.ejecutar()])
                self.db.ventas.delete_one({"_id": "VXreciente"})
        self.venta("VXhoy", fecha=HOY + timedelta(hours=23, minutes=59))
        self.assertNotIn("C001", [c["_id"] for c in q12.ejecutar()])
        self.assertIn("C008", [c["_id"] for c in q12.ejecutar()])

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
        self.venta("VX01", fecha=HOY - timedelta(days=59))
        self.venta("VX02", fecha=HOY - timedelta(days=60))
        self.venta("VX03", fecha=HOY + timedelta(hours=23, minutes=59))
        self.venta("VX04", fecha=HOY + timedelta(days=1))
        self.venta("VX05", estado="Anulada")
        self.venta("VX06", estado="Pendiente", items=[
            {"id_detalle": "DX1", "id_producto": "PRD001", "cantidad": 2, "precio_unit": 10},
            {"id_detalle": "DX2", "id_producto": "PRD002", "cantidad": 3, "precio_unit": 10}])
        self.venta("VX07", id_farmaceutico="F004")
        self.assertEqual({f["id_farmaceutico"]: f["cantidad_ventas"] for f in q05.ejecutar()},
                         {"F001": 3, "F002": 0, "F003": 0, "F005": 0, "F006": 0, "F007": 0})

    def test_q05_ventana_exacta_60_dias(self):
        self.db.ventas.delete_many({})
        for dias in range(61):
            self.venta(f"VX{dias:03d}", fecha=HOY - timedelta(days=dias))
        resultado = {f["id_farmaceutico"]: f["cantidad_ventas"] for f in q05.ejecutar()}
        self.assertEqual(resultado["F001"], 60)

    def test_q11_dataset_mes_vacio_y_octubre(self):
        self.assertEqual(q11.ejecutar(), [])
        with patch.object(q11, "hoy", return_value=datetime(2026, 10, 13)):
            resultado = q11.ejecutar()
        self.assertEqual({f["id_farmaceutico"]: f["ingresos_totales"] for f in resultado},
                         {"F001": 4400, "F002": 7800, "F003": 7100, "F005": 4600})
        for fila in resultado:
            self.assertEqual((fila["anio"], fila["mes"]), (2026, 10))
            self.assertEqual(fila["matricula"], self.db.farmaceuticos.find_one(
                {"_id": fila["id_farmaceutico"]})["matricula"])

    def test_q11_periodo_estados_y_farmaceutico_inactivo(self):
        self.db.ventas.delete_many({})
        self.venta("VX01", fecha=datetime(2026, 10, 31), total=1000)
        self.venta("VX02", fecha=datetime(2026, 11, 1), total=300, id_farmaceutico="F004")
        self.venta("VX03", fecha=datetime(2026, 11, 30), total=200)
        self.venta("VX04", fecha=datetime(2026, 12, 1), total=1000)
        self.venta("VX05", fecha=datetime(2025, 11, 10), total=1000)
        self.venta("VX06", estado="Pendiente", total=1000)
        self.venta("VX07", estado="Anulada", total=1000)
        self.assertEqual({f["id_farmaceutico"]: f["ingresos_totales"] for f in q11.ejecutar()},
                         {"F001": 200, "F004": 300})

    def test_q11_cambio_de_anio_sin_recrear_vista(self):
        self.db.ventas.delete_many({})
        self.venta("VX01", fecha=datetime(2026, 12, 31), total=200)
        self.venta("VX02", fecha=datetime(2027, 1, 1), total=300)
        self.venta("VX03", fecha=datetime(2026, 1, 1), total=400)
        for fecha, esperado in ((datetime(2026, 12, 31), 200), (datetime(2027, 1, 1), 300)):
            with self.subTest(fecha=fecha), patch.object(q11, "hoy", return_value=fecha):
                self.assertEqual([f["ingresos_totales"] for f in q11.ejecutar()], [esperado])

    def test_venta_sin_items_se_rechaza(self):
        tablas = {nombre: {"catedra": [dict(fila) for fila in partes["catedra"]],
                           "propios": []}
                  for nombre, partes in self.tablas.items()}
        venta = tablas["ventas.csv"]["catedra"][0]["id_venta"]
        tablas["detalle_ventas.csv"]["catedra"] = [
            fila for fila in tablas["detalle_ventas.csv"]["catedra"]
            if fila["id_venta"] != venta
        ]
        for fila in tablas["ventas.csv"]["catedra"]:
            if fila["id_venta"] == venta:
                fila["total"] = "0"
        with self.assertRaises(cargar.CargaInvalida) as fallo:
            cargar._validar(tablas)
        self.assertIn("no tiene ítems", str(fallo.exception))

    def test_carga_y_vista_repetibles(self):
        self.cargar()
        self.assertEqual({nombre: self.db[nombre].count_documents({}) for nombre in db.COLECCIONES},
                         {"clientes": 8, "sucursales": 5, "farmaceuticos": 7, "proveedores": 5,
                          "productos": 13, "stock_lotes": 18, "recetas": 9, "ventas": 16})
        self.db.command("collMod", q11.VISTA, viewOn="ventas", pipeline=[])
        q11.crear_vista()
        self.assertEqual(q11.ejecutar(), [])
        with patch.object(q11, "hoy", return_value=datetime(2026, 10, 13)):
            self.assertEqual({f["id_farmaceutico"]: f["ingresos_totales"] for f in q11.ejecutar()},
                             {"F001": 4400, "F002": 7800, "F003": 7100, "F005": 4600})
        vista = next(self.db.list_collections(filter={"name": q11.VISTA}))
        self.assertEqual(vista["type"], "view")
        self.assertEqual(vista["options"]["viewOn"], "ventas")

    def test_q11_refleja_q15_sin_recrear_vista(self):
        self.assertEqual(q11.ejecutar(), [])
        respuesta = q15.ejecutar("V011")
        self.assertTrue(respuesta["ok"], respuesta)
        self.assertEqual(respuesta["documento"]["fecha"], HOY)
        self.assertEqual(respuesta["documento"]["fecha_registro"], datetime(2026, 10, 12))
        self.assertEqual({f["id_farmaceutico"]: f["ingresos_totales"] for f in q11.ejecutar()},
                         {"F006": 4800})
        self.assertFalse(q15.ejecutar("V011")["ok"])
        self.assertEqual(q11.ejecutar()[0]["ingresos_totales"], 4800)


if __name__ == "__main__":
    unittest.main(verbosity=2)
