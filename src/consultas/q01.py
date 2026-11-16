"""q01. Productos activos con todos los datos de su proveedor.

Tipo: lectura
Sin parámetros de entrada.
Motor: MongoDB.
Retorna productos ordenados por id, con el proveedor completo en `proveedor`.
Solo se filtra la actividad del producto.
"""

from db import base

ID = "q01"
TIPO = "lectura"
DESCRIPCION = "Productos activos con todos los datos de su proveedor."


def ejecutar() -> list[dict]:
    return list(base().productos.aggregate([
        {"$match": {"activo": True}},
        {"$lookup": {
            "from": "proveedores", "localField": "id_proveedor",
            "foreignField": "_id", "as": "proveedor",
        }},
        {"$unwind": "$proveedor"},
        {"$sort": {"_id": 1}},
    ]))
