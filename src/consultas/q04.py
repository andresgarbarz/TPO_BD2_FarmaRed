"""q04. Clientes con más de una receta, indicando la cantidad.

Tipo: agregacion
Sin parámetros de entrada.
Motor: MongoDB.
Retorna id_cliente, nombre, apellido, dni y cantidad_recetas, ordenados por id.
Cuenta todas las recetas, sin filtrar tipo, estado ni actividad del cliente.
"""

from db import base

ID = "q04"
TIPO = "agregacion"
DESCRIPCION = "Clientes con más de una receta, indicando la cantidad."


def ejecutar() -> list[dict]:
    return list(base().recetas.aggregate([
        {"$group": {
            "_id": "$id_cliente",
            "cantidad_recetas": {"$sum": 1},
        }},
        {"$match": {"cantidad_recetas": {"$gt": 1}}},
        {"$lookup": {
            "from": "clientes", "localField": "_id",
            "foreignField": "_id", "as": "cliente",
        }},
        {"$unwind": "$cliente"},
        {"$project": {
            "_id": 0, "id_cliente": "$_id",
            "nombre": "$cliente.nombre", "apellido": "$cliente.apellido",
            "dni": "$cliente.dni", "cantidad_recetas": 1,
        }},
        {"$sort": {"id_cliente": 1}},
    ]))
