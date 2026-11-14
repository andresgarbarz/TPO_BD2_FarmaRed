"""q12. Clientes sin ventas registradas en el último año.

Tipo: lectura
Sin parámetros de entrada.
Motor: MongoDB.
Retorna clientes completos ordenados por id, incluidos los inactivos y los que
nunca compraron. Cuenta ventas de cualquier estado, incluidas las anuladas.
Convención: 365 días incluyendo hoy, desde hoy() - 364 días hasta mañana
exclusivo. Usa fecha de la venta, no fecha_registro.
"""

from datetime import timedelta

from db import base, hoy

ID = "q12"
TIPO = "lectura"
DESCRIPCION = "Clientes sin ventas registradas en el último año."


def ejecutar() -> list[dict]:
    fecha = hoy()
    return list(base().clientes.aggregate([
        {"$lookup": {
            "from": "ventas", "localField": "_id",
            "foreignField": "id_cliente", "as": "ventas_recientes",
            "pipeline": [
                {"$match": {
                    "fecha": {"$gte": fecha - timedelta(days=364),
                              "$lt": fecha + timedelta(days=1)},
                }},
                {"$limit": 1},
            ],
        }},
        {"$match": {"ventas_recientes.0": {"$exists": False}}},
        {"$project": {"ventas_recientes": 0}},
        {"$sort": {"_id": 1}},
    ]))
