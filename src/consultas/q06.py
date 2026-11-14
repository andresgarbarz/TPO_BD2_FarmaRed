"""q06. Recetas de tratamiento prolongado vigentes cuya próxima dispensa es anterior a hoy, con los datos del cliente.

Tipo: lectura
Sin parámetros de entrada.
Motor: MongoDB.
Retorna recetas ordenadas por id, con el documento completo del cliente en
`cliente`. Excluye fechas nulas, ausentes, de hoy o futuras. No filtra la
actividad del cliente.
"""

from db import base, hoy

ID = "q06"
TIPO = "lectura"
DESCRIPCION = "Recetas de tratamiento prolongado vigentes cuya próxima dispensa es anterior a hoy, con los datos del cliente."


def ejecutar() -> list[dict]:
    fecha = hoy()
    return list(base().recetas.aggregate([
        {"$match": {
            "tipo": "Tratamiento prolongado",
            "estado": "Vigente",
            "proxima_dispensa": {"$type": "date", "$lt": fecha},
        }},
        {"$lookup": {
            "from": "clientes", "localField": "id_cliente",
            "foreignField": "_id", "as": "cliente",
        }},
        {"$unwind": "$cliente"},
        {"$sort": {"_id": 1}},
    ]))
