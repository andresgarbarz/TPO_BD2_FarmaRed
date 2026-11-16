"""q07. Top 5 productos más vendidos en unidades, solo ventas Completada.

Tipo: agregacion
Sin parámetros de entrada.
Motor: MongoDB.
Retorna id_producto, nombre y unidades_vendidas. Ordena por unidades
descendentes y desempata por id ascendente.
"""

from db import base

ID = "q07"
TIPO = "agregacion"
DESCRIPCION = "Top 5 productos más vendidos en unidades, solo ventas Completada."


def ejecutar() -> list[dict]:
    return list(base().ventas.aggregate([
        {"$match": {"estado": "Completada"}},
        {"$unwind": "$items"},
        {"$group": {
            "_id": "$items.id_producto",
            "unidades_vendidas": {"$sum": "$items.cantidad"},
        }},
        {"$sort": {"unidades_vendidas": -1, "_id": 1}},
        {"$limit": 5},
        {"$lookup": {
            "from": "productos", "localField": "_id",
            "foreignField": "_id", "as": "producto",
        }},
        {"$unwind": "$producto"},
        {"$project": {
            "_id": 0, "id_producto": "$_id", "nombre": "$producto.nombre",
            "unidades_vendidas": 1,
        }},
        {"$sort": {"unidades_vendidas": -1, "id_producto": 1}},
    ]))
