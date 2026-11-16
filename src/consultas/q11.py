"""q11. Ingresos totales por farmacéutico en el mes actual, solo ventas Completada.

Tipo: agregacion
Sin parámetros de entrada.
Motor: MongoDB.
Retorna id_farmaceutico, nombre, apellido, matricula, anio, mes e
ingresos_totales, ordenados por id. No filtra farmacéuticos inactivos.
La carga prepara la vista mensual; ejecutar selecciona el mes de hoy().

"""

from db import base, hoy

ID = "q11"
TIPO = "agregacion"
DESCRIPCION = "Ingresos totales por farmacéutico en el mes actual, solo ventas Completada."


VISTA = "ingresos_mensuales_farmaceutico"


def crear_vista() -> None:
    """Crea o actualiza la vista mensual sin almacenar un mes fijo ni ingresos."""
    db = base()
    pipeline = [
        {"$match": {"estado": "Completada"}},
        {"$group": {
            "_id": {
                "id_farmaceutico": "$id_farmaceutico",
                # Las fechas guardadas son días civiles a medianoche, no instantes locales.
                "anio": {"$year": "$fecha"}, "mes": {"$month": "$fecha"},
            },
            "ingresos_totales": {"$sum": "$total"},
        }},
        {"$project": {
            "_id": 0, "id_farmaceutico": "$_id.id_farmaceutico",
            "anio": "$_id.anio", "mes": "$_id.mes", "ingresos_totales": 1,
        }},
    ]
    if VISTA in db.list_collection_names():
        db.command("collMod", VISTA, viewOn="ventas", pipeline=pipeline)
    else:
        db.create_collection(VISTA, viewOn="ventas", pipeline=pipeline)


def ejecutar() -> list[dict]:
    fecha = hoy()
    return list(base()[VISTA].aggregate([
        {"$match": {"anio": fecha.year, "mes": fecha.month}},
        {"$lookup": {
            "from": "farmaceuticos", "localField": "id_farmaceutico",
            "foreignField": "_id", "as": "farmaceutico",
        }},
        {"$unwind": "$farmaceutico"},
        {"$project": {
            "_id": 0, "id_farmaceutico": 1, "anio": 1, "mes": 1,
            "ingresos_totales": 1, "nombre": "$farmaceutico.nombre",
            "apellido": "$farmaceutico.apellido", "matricula": "$farmaceutico.matricula",
        }},
        {"$sort": {"id_farmaceutico": 1}},
    ]))
