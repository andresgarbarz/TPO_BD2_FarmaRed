"""Los cambios confirmados en Mongo se recuperan aun sin el pedido original."""

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

from bson import ObjectId
from neo4j.exceptions import ServiceUnavailable
from pymongo.collection import Collection
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

import cargar
import db
import grafo
import reglas
from consultas import q02, q10, q11, q13, q14, q15


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
        for modulo in (cargar, grafo, q11, q13, q14, q15, reglas):
            self.enterContext(patch.object(modulo, "base", return_value=self.db))
        for modulo in (q14, q15, reglas):
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
            for nombre, identificador in (("ventas", "V011"), ("recetas", "RC006")):
                self.assertTrue(self.db[nombre].find_one({"_id": identificador})["grafo_pendiente"])
            with self.assertRaises(grafo.GrafoPendiente):
                q02.ejecutar()
        self.assertEqual([v["id_venta"] for v in q02.ejecutar()], ["V012"])
        for nombre, identificador in (("ventas", "V011"), ("recetas", "RC006")):
            self.assertFalse(self.db[nombre].find_one({"_id": identificador})["grafo_pendiente"])
        self.assertEqual(grafo.consultar("MATCH (r:Receta {id:'RC006'}) RETURN r.estado AS estado"),
                         [{"estado": "Completada"}])

    def test_salida_entre_commit_y_proyeccion_no_pierde_el_pendiente(self):
        with patch.object(q13, "proyectar", side_effect=SystemExit("salida del proceso")):
            with self.assertRaises(SystemExit):
                q13.ejecutar("baja", id_cliente="C001")
        documento = self.db.clientes.find_one({"_id": "C001"})
        self.assertFalse(documento["activo"])
        self.assertTrue(documento["grafo_pendiente"])
        cliente = next(c for c in q10.ejecutar("S002") if c["id_cliente"] == "C001")
        self.assertFalse(cliente["activo"])
        self.assertFalse(self.db.clientes.find_one({"_id": "C001"})["grafo_pendiente"])

    def test_confirmacion_vieja_no_borra_un_pendiente_mas_nuevo(self):
        with patch.object(q13, "proyectar", return_value="pendiente"):
            vieja = q13.ejecutar("modificar", id_cliente="C001", telefono="111")["documento"]
            nueva = q13.ejecutar("modificar", id_cliente="C001", telefono="222")["documento"]
        grafo._limpiar_pendiente("clientes", vieja)
        self.assertTrue(self.db.clientes.find_one({"_id": "C001"})["grafo_pendiente"])
        grafo.recuperar_pendientes()
        self.assertEqual(grafo.consultar(
            "MATCH (c:Cliente {id:'C001'}) RETURN c.telefono AS telefono, c._version AS version"),
            [{"telefono": "222", "version": nueva["_version"]}])

    def test_pendiente_heredado_sin_version_se_confirma_como_version_cero(self):
        self.db.clientes.update_one({"_id": "C001"},
                                    {"$unset": {"_version": ""}, "$set": {"grafo_pendiente": True}})
        grafo.recuperar_pendientes()
        self.assertFalse(self.db.clientes.find_one({"_id": "C001"})["grafo_pendiente"])

    def test_cambios_durante_recuperacion_rechazan_lectura_atrasada(self):
        with patch.object(q13, "proyectar", return_value="pendiente"):
            q13.ejecutar("modificar", id_cliente="C001", telefono="111")
        limpiar = grafo._limpiar_pendiente
        cambio = False

        def actualizar(nombre, documento):
            nonlocal cambio
            if nombre == "clientes" and not cambio:
                cambio = True
                with patch.object(q13, "proyectar", return_value="pendiente"):
                    q13.ejecutar("baja", id_cliente="C001")
            limpiar(nombre, documento)

        with patch.object(grafo, "_limpiar_pendiente", actualizar):
            with self.assertRaises(grafo.GrafoPendiente):
                q10.ejecutar("S002")
        cliente = next(c for c in q10.ejecutar("S002") if c["id_cliente"] == "C001")
        self.assertFalse(cliente["activo"])

    def test_reconstruccion_no_pierde_escrituras_proyectadas_despues_de_la_foto(self):
        reconstruir = grafo._reconstruir
        for operacion in ("alta", "baja"):
            with self.subTest(operacion=operacion):
                cambios = []

                def escribir_despues_de_la_foto(tx, datos):
                    if not cambios:
                        if operacion == "alta":
                            respuesta = q13.ejecutar(
                                "alta", nombre="Ana", apellido="Prueba", dni="99900022",
                                email="ana@example.test", telefono="123", ciudad="CABA",
                                provincia="Buenos Aires", obra_social="Sin cobertura")
                        else:
                            respuesta = q13.ejecutar("baja", id_cliente="C001")
                        self.assertTrue(respuesta["ok"], respuesta)
                        self.assertNotIn("aviso_grafo", respuesta)
                        cambios.append(respuesta["documento"])
                        self.assertFalse(self.db.clientes.find_one(
                            {"_id": cambios[0]["_id"]})["grafo_pendiente"])
                    reconstruir(tx, datos)

                with patch.object(grafo, "_reconstruir", escribir_despues_de_la_foto):
                    grafo.reconstruir()
                documento = cambios[0]
                self.assertTrue(self.db.clientes.find_one(
                    {"_id": documento["_id"]})["grafo_pendiente"])
                self.assertEqual(grafo.consultar(
                    "MATCH (c:Cliente {id: $id}) RETURN c.activo AS activo, c._version AS version",
                    id=documento["_id"]),
                    [{"activo": documento["activo"], "version": documento["_version"]}])

    def test_salida_despues_del_commit_de_reconstruccion_conserva_el_reintento(self):
        reconstruir = grafo._reconstruir
        actualizar = Collection.update_many
        cambios = []

        def escribir_despues_de_la_foto(tx, datos):
            if not cambios:
                cambios.append(q13.ejecutar("baja", id_cliente="C001"))
                self.assertTrue(cambios[0]["ok"], cambios[0])
                self.assertNotIn("aviso_grafo", cambios[0])
            reconstruir(tx, datos)

        def interrumpir(coleccion, filtro, cambio, *args, **kwargs):
            if (coleccion.database.name == self.db.name and coleccion.name == "clientes"
                    and cambio == {"$set": {"grafo_pendiente": True}}):
                raise SystemExit("salida después del commit de Neo4j")
            return actualizar(coleccion, filtro, cambio, *args, **kwargs)

        with patch.object(grafo, "_reconstruir", escribir_despues_de_la_foto),                 patch.object(Collection, "update_many", interrumpir):
            with self.assertRaises(SystemExit):
                grafo.reconstruir()
        estado = self.db["_estado_grafo"].find_one({"_id": "reconstruccion"})
        self.assertIsNotNone(estado)
        self.assertTrue(estado["carga_lista"])
        self.assertFalse(self.db.clientes.find_one({"_id": "C001"})["grafo_pendiente"])
        cliente = next(c for c in q10.ejecutar("S002") if c["id_cliente"] == "C001")
        self.assertFalse(cliente["activo"])
        self.assertIsNone(self.db["_estado_grafo"].find_one({"_id": "reconstruccion"}))

    def test_recarga_fallida_se_recupera_sin_conservar_nodos_de_la_carga_vieja(self):
        alta = q13.ejecutar("alta", nombre="Ana", apellido="Prueba", dni="99900011",
                            email="ana@example.test", telefono="123", ciudad="CABA",
                            provincia="Buenos Aires", obra_social="Sin cobertura")
        self.assertTrue(alta["ok"], alta)
        with patch.object(cargar, "_leer_todo", return_value=self.tablas), \
                patch.object(grafo, "_sesion", side_effect=ServiceUnavailable("caído")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(cargar.main(), 1)
        self.assertIsNone(self.db.clientes.find_one({"_id": alta["documento"]["_id"]}))
        self.assertIsNotNone(self.db["_estado_grafo"].find_one({"_id": "reconstruccion"}))
        self.assertEqual([v["id_venta"] for v in q02.ejecutar()], ["V012", "V011"])
        self.assertEqual(grafo.consultar("MATCH (n) RETURN count(n) AS cantidad"), [{"cantidad": 58}])
        self.assertIsNone(self.db["_estado_grafo"].find_one({"_id": "reconstruccion"}))
        self.assertFalse(any(self.db[nombre].find_one({"grafo_pendiente": True})
                             for nombre in grafo.COLECCIONES_PENDIENTES))

    def test_reconstruccion_vieja_no_confirma_una_recarga_nueva(self):
        with redirect_stdout(io.StringIO()):
            cargar._escribir(self.tablas)
        limpiar = grafo._limpiar_pendiente
        token = ObjectId()
        cambio = False

        def recargar(nombre, documento):
            nonlocal cambio
            if not cambio:
                cambio = True
                self.db["_estado_grafo"].update_one({"_id": "reconstruccion"}, {"$set": {"generacion": token}})
            limpiar(nombre, documento)

        with patch.object(grafo, "_limpiar_pendiente", recargar):
            with self.assertRaises(grafo.GrafoPendiente):
                q02.ejecutar()
        self.assertEqual(self.db["_estado_grafo"].find_one({"_id": "reconstruccion"})["generacion"], token)
        grafo.recuperar_pendientes()
        self.assertIsNone(self.db["_estado_grafo"].find_one({"_id": "reconstruccion"}))

    def test_carga_interrumpida_no_publica_un_grafo_parcial(self):
        insertar = Collection.insert_many

        def fallar(coleccion, documentos, *args, **kwargs):
            if coleccion.database.name == self.db.name and coleccion.name == "sucursales":
                raise OperationFailure("corte durante la carga")
            return insertar(coleccion, documentos, *args, **kwargs)

        with patch.object(Collection, "insert_many", fallar), redirect_stdout(io.StringIO()):
            with self.assertRaises(OperationFailure):
                cargar._escribir(self.tablas)
        self.assertFalse(self.db["_estado_grafo"].find_one({"_id": "reconstruccion"})["carga_lista"])
        with self.assertRaisesRegex(grafo.GrafoPendiente, "carga incompleta"):
            q02.ejecutar()
        with redirect_stdout(io.StringIO()):
            cargar._escribir(self.tablas)
        self.assertEqual([v["id_venta"] for v in q02.ejecutar()], ["V012", "V011"])

    def test_sin_mongo_no_se_sirve_un_grafo_de_actualidad_desconocida(self):
        with patch.object(grafo, "base", side_effect=ServerSelectionTimeoutError("caído")):
            with self.assertRaises(grafo.GrafoPendiente):
                q02.ejecutar()
