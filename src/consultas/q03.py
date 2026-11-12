"""q03. Historial de un cliente: ventas y recetas ordenadas por fecha.

Tipo: lectura
Parámetro: id_cliente.
Motor: Neo4j

Propósito: devolver los eventos de un cliente mezclando ventas y recetas en una
sola línea de tiempo. Las ventas usan fecha y las recetas fecha_emision.

Valor de retorno:
    list[dict] ordenada por fecha. Cada fila trae tipo_evento ("venta" o
    "receta"), id, fecha, estado, total (solo ventas) y detalle (tipo de venta o
    de receta). Si el cliente no existe o no tiene eventos, devuelve []. Si Neo4j
    no está disponible, levanta GrafoPendiente.
"""

from grafo import consultar


ID = "q03"
TIPO = "lectura"
DESCRIPCION = "Historial de un cliente: ventas y recetas ordenadas por fecha."

CONSULTA = """
MATCH (c:Cliente {id: $id_cliente})
CALL (c) {
    MATCH (c)-[:REALIZO]->(v:Venta)
    RETURN 'venta' AS tipo_evento, v.id AS id, v.fecha AS fecha,
           v.estado AS estado, v.total AS total, v.tipo AS detalle
    UNION ALL
    MATCH (c)<-[:PRESCRIPTA_A]-(r:Receta)
    RETURN 'receta' AS tipo_evento, r.id AS id, r.fecha_emision AS fecha,
           r.estado AS estado, null AS total, r.tipo AS detalle
}
RETURN tipo_evento, id, fecha, estado, total, detalle
ORDER BY fecha, tipo_evento, id
"""


def ejecutar(id_cliente: str) -> list[dict]:
    return consultar(CONSULTA, id_cliente=id_cliente)
