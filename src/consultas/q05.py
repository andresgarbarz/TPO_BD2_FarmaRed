"""q05. Farmacéuticos activos y cantidad de ventas de los últimos 60 días, sin anuladas, incluyendo los que tienen cero.

Tipo: agregacion
Sin parámetros de entrada.
Motor: MongoDB.
Retorna id_farmaceutico, nombre, apellido, matricula y cantidad_ventas,
ordenados por id. Incluye pendientes y farmacéuticos sin ventas.
Convención: 60 días incluyendo hoy, desde hoy() - 59 días hasta mañana exclusivo.

"""

from datetime import timedelta

from db import base, hoy

ID = "q05"
TIPO = "agregacion"
DESCRIPCION = "Farmacéuticos activos y cantidad de ventas de los últimos 60 días, sin anuladas, incluyendo los que tienen cero."


def ejecutar() -> list[dict]:
    fecha = hoy()
    return list(base().farmaceuticos.aggregate([
        {"$match": {"activo": True}},
        {"$lookup": {
            "from": "ventas", "localField": "_id",
            "foreignField": "id_farmaceutico", "as": "ventas",
            "pipeline": [
                {"$match": {
                    "estado": {"$ne": "Anulada"},
                    "fecha": {"$gte": fecha - timedelta(days=59),
                              "$lt": fecha + timedelta(days=1)},
                }},
                {"$count": "cantidad"},
            ],
        }},
        {"$project": {
            "_id": 0, "id_farmaceutico": "$_id",
            "nombre": 1, "apellido": 1, "matricula": 1,
            "cantidad_ventas": {"$ifNull": [{"$first": "$ventas.cantidad"}, 0]},
        }},
        {"$sort": {"id_farmaceutico": 1}},
    ]))
