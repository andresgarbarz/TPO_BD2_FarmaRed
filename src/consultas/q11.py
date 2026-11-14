"""q11. Ingresos totales por farmacéutico en el mes actual, solo ventas Completada.

Tipo: agregacion
Sin parámetros de entrada.
Motor: MongoDB.
Retorna id_farmaceutico, nombre, apellido, matricula, anio, mes e
ingresos_totales, ordenados por id. No filtra farmacéuticos inactivos.
La vista acumula por fecha; ejecutar filtra el mes de hoy() y suma sus ingresos.
[P18, pp. 5–6; T13, pp. 50–52]
"""

from db import base, hoy

ID = "q11"
TIPO = "agregacion"
DESCRIPCION = "Ingresos totales por farmacéutico en el mes actual, solo ventas Completada."


VISTA = "ingresos_mensuales_farmaceutico"


def crear_vista() -> None:
    """Agrupa por fecha para que el filtro del mes pueda usar el índice de ventas."""
    db = base()
    pipeline = [
        {"$match": {"estado": "Completada"}},
        {"$group": {
            "_id": {
                "id_farmaceutico": "$id_farmaceutico",
                "fecha": "$fecha",
            },
            "ingresos_totales": {"$sum": "$total"},
        }},
        {"$project": {
            "_id": 0, "id_farmaceutico": "$_id.id_farmaceutico",
            "fecha": "$_id.fecha", "ingresos_totales": 1,
        }},
    ]
    if VISTA in db.list_collection_names():
        db.command("collMod", VISTA, viewOn="ventas", pipeline=pipeline)
    else:
        db.create_collection(VISTA, viewOn="ventas", pipeline=pipeline)


def ejecutar() -> list[dict]:
    fecha = hoy()
    inicio = fecha.replace(day=1)
    if inicio.month == 12:
        fin = inicio.replace(year=inicio.year + 1, month=1)
    else:
        fin = inicio.replace(month=inicio.month + 1)
    return list(base()[VISTA].aggregate([
        {"$match": {"fecha": {"$gte": inicio, "$lt": fin}}},
        {"$group": {"_id": "$id_farmaceutico",
                    "ingresos_totales": {"$sum": "$ingresos_totales"}}},
        {"$project": {"_id": 0, "id_farmaceutico": "$_id", "ingresos_totales": 1}},
        {"$lookup": {
            "from": "farmaceuticos", "localField": "id_farmaceutico",
            "foreignField": "_id", "as": "farmaceutico",
        }},
        {"$unwind": "$farmaceutico"},
        {"$project": {
            "_id": 0, "id_farmaceutico": 1,
            "anio": {"$literal": fecha.year}, "mes": {"$literal": fecha.month},
            "ingresos_totales": 1, "nombre": "$farmaceutico.nombre",
            "apellido": "$farmaceutico.apellido", "matricula": "$farmaceutico.matricula",
        }},
        {"$sort": {"id_farmaceutico": 1}},
    ]))
