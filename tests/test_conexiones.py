"""El pool compartido se reutiliza, incluso al abrirlo desde varios hilos."""

import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from pymongo.errors import InvalidOperation

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

import db
from consultas import q09


class ConexionesMongo(unittest.TestCase):
    def setUp(self):
        db.cerrar()
        self.enterContext(patch.object(db, "BASE", f"farmared_test_{uuid4().hex}"))
        self.addCleanup(db.cerrar)
        self.cliente = db.cliente()
        self.addCleanup(self.cliente.close)
        self.addCleanup(self.cliente.drop_database, db.BASE)
        self.cliente.admin.command("ping")

    def test_varias_consultas_reutilizan_un_cliente(self):
        with patch.object(db, "cliente", wraps=db.cliente) as crear:
            primera = db.base()
            primera.ventas.insert_one({"_id": "VX", "tipo": "Venta libre",
                                       "total": 100, "estado": "Completada"})
            for _ in range(5):
                self.assertIs(db.base().client, primera.client)
                self.assertEqual([v["_id"] for v in q09.ejecutar()], ["VX"])
            self.assertEqual(crear.call_count, 1)

    def test_apertura_concurrente_crea_un_solo_pool(self):
        barrera = Barrier(8)

        def abrir(_):
            barrera.wait(timeout=10)
            base = db.base()
            base.client.admin.command("ping")
            return base.client

        with patch.object(db, "cliente", wraps=db.cliente) as crear:
            with ThreadPoolExecutor(max_workers=8) as pool:
                clientes = list(pool.map(abrir, range(8)))
            self.assertTrue(all(c is clientes[0] for c in clientes))
            self.assertEqual(crear.call_count, 1)

    def test_cerrar_reabre_y_no_cierra_clientes_propios(self):
        anterior = db.base().client
        propio = db.cliente()
        self.addCleanup(propio.close)
        self.assertIsNot(propio, anterior)
        db.cerrar()
        db.cerrar()
        with self.assertRaises(InvalidOperation):
            anterior.admin.command("ping")
        propio.admin.command("ping")
        nueva = db.base().client
        self.assertIsNot(nueva, anterior)
        nueva.admin.command("ping")
        propio.close()
        nueva.admin.command("ping")
