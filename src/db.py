"""Conexión a MongoDB y la fecha que usan las escrituras.

Las URIs salen del entorno. Fuera de Codespaces el defecto es localhost.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from pymongo import MongoClient
from pymongo.database import Database

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017")
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
BASE = "farmared"

COLECCIONES = (
    "clientes",
    "sucursales",
    "farmaceuticos",
    "proveedores",
    "productos",
    "stock_lotes",
    "recetas",
    "ventas",
)

ZONA = ZoneInfo("America/Argentina/Buenos_Aires")


def cliente() -> MongoClient:
    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)


def base() -> Database:
    return cliente()[BASE]


def hoy() -> datetime:
    """Fecha de Argentina a medianoche, sin correr el día por UTC.

    Se arma con año, mes y día, igual que las fechas de la carga.
    Entre las 21 y las 24 en Argentina, UTC ya es el día siguiente.
    """
    ahora = datetime.now(ZONA)
    return datetime(ahora.year, ahora.month, ahora.day)


def fecha_de_partes(texto: str) -> datetime:
    """Arma un Date con año, mes y día. No parsea el ISO completo."""
    anio, mes, dia = (int(parte) for parte in texto.split("-"))
    return datetime(anio, mes, dia)
