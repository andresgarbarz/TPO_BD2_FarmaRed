"""q10. Clientes atendidos en una sucursal.

Tipo: lectura
Parámetro: id_sucursal.
Motor: Neo4j

Propósito: recorrer Cliente -> Venta -> Sucursal y Venta <- Farmaceutico y
devolver los clientes atendidos en la sucursal indicada. No filtra farmacéuticos
activos: la consigna pide incluirlos estén activos o no.

Valor de retorno:
    list[dict] sin clientes repetidos, ordenada por apellido y nombre. Si la
    sucursal no existe o no tiene ventas, devuelve []. Si Neo4j no está
    disponible, levanta GrafoPendiente.
"""

from grafo import consultar


ID = "q10"
TIPO = "lectura"
DESCRIPCION = "Clientes atendidos en una sucursal a través del farmacéutico."

CONSULTA = """
MATCH (c:Cliente)-[:REALIZO]->(v:Venta)-[:EN_SUCURSAL]->(s:Sucursal {id: $id_sucursal})
MATCH (f:Farmaceutico)-[:ATENDIO]->(v)
RETURN DISTINCT c.id AS id_cliente, c.nombre AS nombre,
       c.apellido AS apellido, c.dni AS dni, c.activo AS activo
ORDER BY c.apellido, c.nombre
"""


def ejecutar(id_sucursal: str) -> list[dict]:
    return consultar(CONSULTA, id_sucursal=id_sucursal)
