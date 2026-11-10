"""q09. Ventas de tipo Venta libre con total menor a 5000, sin anuladas.

Tipo: lectura
Sin parámetros de entrada.
Motor: MongoDB.
Retorna una lista de ventas completas, ordenadas por id. Incluye pendientes.
[P18, p. 6]
"""

from db import base

ID = "q09"
TIPO = "lectura"
DESCRIPCION = "Ventas de tipo Venta libre con total menor a 5000, sin anuladas."


def ejecutar() -> list[dict]:
    return list(base().ventas.find({
        "tipo": "Venta libre",
        "total": {"$lt": 5000},
        "estado": {"$ne": "Anulada"},
    }).sort("_id", 1))
