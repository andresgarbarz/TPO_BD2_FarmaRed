"""q08. Lotes con menos de 50 unidades, con producto, sucursal y proveedor.

Tipo: lectura
Sin parámetros de entrada.
Motor: MongoDB.
Retorna lotes ordenados por id, con documentos `producto`, `sucursal` y
`proveedor`. Incluye vencidos, stock cero y entidades inactivas.
[P18, p. 6; T14, pp. 21–24]
"""

from db import base

ID = "q08"
TIPO = "lectura"
DESCRIPCION = "Lotes con menos de 50 unidades, con producto, sucursal y proveedor."


def ejecutar() -> list[dict]:
    return list(base().stock_lotes.aggregate([
        {"$match": {"unidades": {"$lt": 50}}},
        {"$lookup": {
            "from": "productos", "localField": "id_producto",
            "foreignField": "_id", "as": "producto",
        }},
        {"$unwind": "$producto"},
        {"$lookup": {
            "from": "sucursales", "localField": "id_sucursal",
            "foreignField": "_id", "as": "sucursal",
        }},
        {"$unwind": "$sucursal"},
        {"$lookup": {
            "from": "proveedores", "localField": "producto.id_proveedor",
            "foreignField": "_id", "as": "proveedor",
        }},
        {"$unwind": "$proveedor"},
        {"$sort": {"_id": 1}},
    ]))
