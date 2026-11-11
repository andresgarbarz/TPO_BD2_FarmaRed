"""q02. Ventas Pendiente con el farmacéutico y la sucursal.

Tipo: lectura
Sin parámetros de entrada.
Motor: Neo4j

Propósito: listar las ventas en estado Pendiente y, para cada una, el
farmacéutico que la atendió con su nombre, apellido, matrícula y la sucursal
donde trabaja.

Valor de retorno:
    list[dict] ordenada por fecha e id de venta. Cada fila trae id_venta, fecha,
    total y los datos del farmacéutico y de la sucursal.
"""

from grafo import consultar


ID = "q02"
TIPO = "lectura"
DESCRIPCION = "Ventas Pendiente con el farmacéutico y la sucursal."

CONSULTA = """
MATCH (f:Farmaceutico)-[:ATENDIO]->(v:Venta {estado: 'Pendiente'})
MATCH (f)-[:TRABAJA_EN]->(s:Sucursal)
RETURN v.id AS id_venta, v.fecha AS fecha, v.total AS total,
       f.id AS id_farmaceutico, f.nombre AS nombre_farmaceutico,
       f.apellido AS apellido_farmaceutico, f.matricula AS matricula,
       s.id AS id_sucursal, s.nombre AS nombre_sucursal
ORDER BY v.fecha, v.id
"""


def ejecutar() -> list[dict]:
    return consultar(CONSULTA)
