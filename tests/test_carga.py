"""Los CSV inválidos se rechazan antes de reemplazar la base existente."""

import copy
import io
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
from consultas import q11


class CargaValidada(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cliente = db.cliente()
        cls.addClassCleanup(cls.cliente.close)
        cls.cliente.admin.command("ping")
        cls.db = cls.cliente[f"farmared_test_carga_{uuid4().hex}"]
        cls.addClassCleanup(cls.cliente.drop_database, cls.db.name)
        cls.tablas = {
            nombre: {"catedra": cargar._leer(cargar.DATOS / nombre, nombre, True), "propios": []}
            for nombre in cargar.ARCHIVOS
        }

    def setUp(self):
        self.enterContext(patch.object(cargar, "base", return_value=self.db))
        self.enterContext(patch.object(q11, "base", return_value=self.db))
        with redirect_stdout(io.StringIO()):
            cargar._escribir(self.tablas)
        self.db.clientes.insert_one({"_id": "preservar", "dni": "no-borrar"})
        self.antes = self.snapshot()

    def snapshot(self):
        return {nombre: list(self.db[nombre].find()) for nombre in db.COLECCIONES}

    def rechaza_sin_escribir(self, tablas):
        with self.assertRaises(cargar.CargaInvalida):
            cargar._escribir(tablas)
        self.assertEqual(self.snapshot(), self.antes)

    def test_rechaza_tipos_rangos_dominios_y_fechas_antes_de_borrar(self):
        casos = [
            ("stock_lotes.csv", "vencimiento", "2026-02-30"),
            ("stock_lotes.csv", "vencimiento", "2026-2-01"),
            ("stock_lotes.csv", "unidades", "no-numérico"),
            ("stock_lotes.csv", "unidades", "-1"),
            ("stock_lotes.csv", "unidades", str(2 ** 63)),
            ("productos.csv", "precio_unit", "-1"),
            ("productos.csv", "precio_unit", "1.5"),
            ("detalle_ventas.csv", "cantidad", "0"),
            ("detalle_ventas.csv", "cantidad", "-1"),
            ("detalle_ventas.csv", "precio_unit", "-1"),
            ("clientes.csv", "activo", "true"),
            ("clientes.csv", "nombre", "   "),
            ("clientes.csv", "obra_social", "inexistente"),
            ("clientes.csv", "nro_afiliado", ""),
            ("sucursales.csv", "tipo", "Depósito"),
            ("farmaceuticos.csv", "cargo", "Cajero"),
            ("proveedores.csv", "tipo", "inexistente"),
            ("productos.csv", "condicion_venta", "inexistente"),
            ("recetas.csv", "estado", "inexistente"),
            ("recetas.csv", "tipo", "inexistente"),
            ("recetas.csv", "dispensas_realizadas", "2"),
            ("recetas.csv", "dispensas_autorizadas", "4"),
            ("ventas.csv", "estado", "inexistente"),
            ("ventas.csv", "medio_pago", "inexistente"),
            ("ventas.csv", "tipo", "Venta libre"),
            ("ventas.csv", "id_cliente", "C999"),
            ("ventas.csv", "id_cliente", "C001"),
            ("ventas.csv", "total", "0"),
        ]
        for nombre, campo, valor in casos:
            with self.subTest(archivo=nombre, campo=campo, valor=valor):
                tablas = copy.deepcopy(self.tablas)
                tablas[nombre]["catedra"][0][campo] = valor
                self.rechaza_sin_escribir(tablas)

    def test_rechaza_estructura_incompleta_y_ids_repetidos(self):
        for origen in ("catedra", "propios"):
            with self.subTest(origen=origen):
                tablas = copy.deepcopy(self.tablas)
                tablas["stock_lotes.csv"][origen].append(dict(tablas["stock_lotes.csv"]["catedra"][0]))
                self.rechaza_sin_escribir(tablas)
        for cambio in ("archivo", "columna", "valor"):
            with self.subTest(cambio=cambio):
                tablas = copy.deepcopy(self.tablas)
                if cambio == "archivo":
                    del tablas["stock_lotes.csv"]
                elif cambio == "columna":
                    del tablas["stock_lotes.csv"]["catedra"][0]["unidades"]
                else:
                    tablas["stock_lotes.csv"]["catedra"][0]["unidades"] = None
                self.rechaza_sin_escribir(tablas)

    def test_rechaza_documento_bson_demasiado_grande_antes_de_borrar(self):
        tablas = copy.deepcopy(self.tablas)
        tablas["clientes.csv"]["catedra"][0]["nombre"] = "A" * (16 * 1024 * 1024)
        self.rechaza_sin_escribir(tablas)

    def test_datos_oficiales_se_convierten_sin_mutarlos_y_carga_repetible(self):
        originales = copy.deepcopy(self.tablas)
        convertidas = cargar._validar(self.tablas)
        self.assertEqual(self.tablas, originales)
        self.assertIs(convertidas["clientes.csv"]["catedra"][0]["activo"], True)
        self.assertIsInstance(convertidas["stock_lotes.csv"]["catedra"][0]["unidades"], int)
        self.assertIsNone(convertidas["clientes.csv"]["catedra"][-1]["nro_afiliado"])
        with redirect_stdout(io.StringIO()):
            cargar._escribir(self.tablas)
            primera = self.snapshot()
            cargar._escribir(self.tablas)
        self.assertEqual(self.snapshot(), primera)
        self.assertEqual(sum(len(v["items"]) for v in primera["ventas"]), 22)
        self.assertEqual(primera["ventas"][0]["id_sucursal"], "S002")
        self.assertFalse(self.db.farmaceuticos.find_one({"_id": "F004"})["activo"])
