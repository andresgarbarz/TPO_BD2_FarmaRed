"""Proyección a Neo4j y consultas Cypher de las relaciones del TPO.

Mongo es la fuente de verdad. La carga completa llama a proyectar_todo, que crea
los constraints, vacía el grafo y lo reconstruye desde Mongo en una transacción.
Las escrituras individuales de q13, q14 y q15 llaman a upsert_cliente,
upsert_venta y upsert_receta, que usan MERGE para no duplicar nodos ni relaciones.

Si una proyección falla, la escritura en Mongo ya está confirmada: proyectar
devuelve el aviso y no propaga el error. consultar expone una lectura Cypher
parametrizada para q02, q03 y q10.
"""

from contextlib import contextmanager
from datetime import date, datetime

from neo4j import GraphDatabase

from db import NEO4J_URI, base

ETIQUETAS = ("Cliente", "Sucursal", "Farmaceutico", "Producto", "Receta", "Venta")


class GrafoPendiente(Exception):
    """Neo4j no está disponible o la proyección no se pudo aplicar."""


@contextmanager
def _driver():
    driver = GraphDatabase.driver(
        NEO4J_URI,
        connection_timeout=3,
        connection_acquisition_timeout=3,
        max_transaction_retry_time=0,
    )
    try:
        yield driver
    finally:
        driver.close()


@contextmanager
def _sesion():
    with _driver() as driver:
        with driver.session() as sesion:
            yield sesion


def _fecha(valor):
    """Convierte un datetime de Mongo al tipo date que espera Neo4j."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return valor


def _crear_constraints(sesion) -> None:
    for etiqueta in ETIQUETAS:
        nombre = f"{etiqueta.lower()}_id"
        sesion.run(
            f"CREATE CONSTRAINT {nombre} IF NOT EXISTS "
            f"FOR (n:{etiqueta}) REQUIRE n.id IS UNIQUE"
        ).consume()


def _upsert_sucursal(tx, documento: dict) -> None:
    tx.run(
        """
        MERGE (s:Sucursal {id: $id})
        SET s.nombre = $nombre,
            s.tipo = $tipo,
            s.direccion = $direccion,
            s.ciudad = $ciudad,
            s.provincia = $provincia,
            s.telefono = $telefono,
            s.activo = $activo
        """,
        id=documento["_id"],
        nombre=documento["nombre"],
        tipo=documento["tipo"],
        direccion=documento["direccion"],
        ciudad=documento["ciudad"],
        provincia=documento["provincia"],
        telefono=documento["telefono"],
        activo=documento["activo"],
    ).consume()


def _upsert_farmaceutico(tx, documento: dict) -> None:
    tx.run(
        """
        MERGE (f:Farmaceutico {id: $id})
        SET f.nombre = $nombre,
            f.apellido = $apellido,
            f.matricula = $matricula,
            f.cargo = $cargo,
            f.activo = $activo
        WITH f
        MERGE (s:Sucursal {id: $id_sucursal})
        MERGE (f)-[:TRABAJA_EN]->(s)
        """,
        id=documento["_id"],
        nombre=documento["nombre"],
        apellido=documento["apellido"],
        matricula=documento["matricula"],
        cargo=documento["cargo"],
        activo=documento["activo"],
        id_sucursal=documento["id_sucursal"],
    ).consume()


def _upsert_producto(tx, documento: dict) -> None:
    tx.run(
        """
        MERGE (p:Producto {id: $id})
        SET p.nombre = $nombre,
            p.principio_activo = $principio_activo,
            p.categoria = $categoria,
            p.presentacion = $presentacion,
            p.condicion_venta = $condicion_venta,
            p.precio_unit = $precio_unit,
            p.activo = $activo
        """,
        id=documento["_id"],
        nombre=documento["nombre"],
        principio_activo=documento["principio_activo"],
        categoria=documento["categoria"],
        presentacion=documento["presentacion"],
        condicion_venta=documento["condicion_venta"],
        precio_unit=documento["precio_unit"],
        activo=documento["activo"],
    ).consume()


def _upsert_cliente(tx, documento: dict) -> None:
    tx.run(
        """
        MERGE (c:Cliente {id: $id})
        SET c.nombre = $nombre,
            c.apellido = $apellido,
            c.dni = $dni,
            c.email = $email,
            c.telefono = $telefono,
            c.ciudad = $ciudad,
            c.provincia = $provincia,
            c.obra_social = $obra_social,
            c.nro_afiliado = $nro_afiliado,
            c.activo = $activo
        """,
        id=documento["_id"],
        nombre=documento["nombre"],
        apellido=documento["apellido"],
        dni=documento["dni"],
        email=documento["email"],
        telefono=documento["telefono"],
        ciudad=documento["ciudad"],
        provincia=documento["provincia"],
        obra_social=documento["obra_social"],
        nro_afiliado=documento.get("nro_afiliado"),
        activo=documento["activo"],
    ).consume()


def _upsert_receta(tx, documento: dict) -> None:
    tx.run(
        """
        MERGE (r:Receta {id: $id})
        SET r.medico = $medico,
            r.matricula_medico = $matricula_medico,
            r.fecha_emision = $fecha_emision,
            r.tipo = $tipo,
            r.dispensas_autorizadas = $dispensas_autorizadas,
            r.dispensas_realizadas = $dispensas_realizadas,
            r.proxima_dispensa = $proxima_dispensa,
            r.estado = $estado
        WITH r
        MERGE (c:Cliente {id: $id_cliente})
        MERGE (r)-[:PRESCRIPTA_A]->(c)
        """,
        id=documento["_id"],
        medico=documento["medico"],
        matricula_medico=documento["matricula_medico"],
        fecha_emision=_fecha(documento["fecha_emision"]),
        tipo=documento["tipo"],
        dispensas_autorizadas=documento["dispensas_autorizadas"],
        dispensas_realizadas=documento["dispensas_realizadas"],
        proxima_dispensa=_fecha(documento.get("proxima_dispensa")),
        estado=documento["estado"],
        id_cliente=documento["id_cliente"],
    ).consume()


def _items_agrupados(items: list[dict]) -> list[dict]:
    """Suma cantidades si una venta repite el mismo producto."""
    agrupados: dict[str, dict] = {}
    orden: list[str] = []
    for item in items:
        id_producto = item["id_producto"]
        if id_producto not in agrupados:
            agrupados[id_producto] = {
                "id_producto": id_producto,
                "cantidad": item["cantidad"],
                "precio_unit": item["precio_unit"],
            }
            orden.append(id_producto)
        else:
            agrupados[id_producto]["cantidad"] += item["cantidad"]
    return [agrupados[id_producto] for id_producto in orden]


def _upsert_venta(tx, documento: dict) -> None:
    id_venta = documento.get("_id") or documento["id_venta"]
    tx.run(
        """
        MERGE (v:Venta {id: $id})
        SET v.fecha = $fecha,
            v.tipo = $tipo,
            v.medio_pago = $medio_pago,
            v.total = $total,
            v.estado = $estado,
            v.fecha_registro = $fecha_registro
        WITH v
        MERGE (c:Cliente {id: $id_cliente})
        MERGE (c)-[:REALIZO]->(v)
        WITH v
        MERGE (f:Farmaceutico {id: $id_farmaceutico})
        MERGE (f)-[:ATENDIO]->(v)
        """,
        id=id_venta,
        fecha=_fecha(documento["fecha"]),
        tipo=documento["tipo"],
        medio_pago=documento["medio_pago"],
        total=documento["total"],
        estado=documento["estado"],
        fecha_registro=_fecha(documento.get("fecha_registro")),
        id_cliente=documento["id_cliente"],
        id_farmaceutico=documento["id_farmaceutico"],
    ).consume()

    id_receta = documento.get("id_receta")
    if id_receta:
        tx.run(
            """
            MATCH (v:Venta {id: $id_venta})
            MERGE (r:Receta {id: $id_receta})
            MERGE (v)-[:CON_RECETA]->(r)
            """,
            id_venta=id_venta,
            id_receta=id_receta,
        ).consume()

    items = _items_agrupados(documento.get("items", []))
    if items:
        tx.run(
            """
            MATCH (v:Venta {id: $id_venta})
            UNWIND $items AS item
            MERGE (p:Producto {id: item.id_producto})
            MERGE (v)-[i:INCLUYE]->(p)
            SET i.cantidad = item.cantidad,
                i.precio_unit = item.precio_unit
            """,
            id_venta=id_venta,
            items=items,
        ).consume()


def upsert_cliente(documento: dict) -> None:
    """Crea o actualiza el nodo del cliente."""
    with _sesion() as sesion:
        sesion.execute_write(_upsert_cliente, documento)


def upsert_venta(documento: dict) -> None:
    """Crea o actualiza la venta y sus relaciones."""
    with _sesion() as sesion:
        sesion.execute_write(_upsert_venta, documento)


def upsert_receta(documento: dict) -> None:
    """Crea o actualiza la receta y su relación con el cliente."""
    with _sesion() as sesion:
        sesion.execute_write(_upsert_receta, documento)


def _reconstruir(tx, datos: dict[str, list[dict]]) -> None:
    tx.run("MATCH (n) DETACH DELETE n").consume()
    for documento in datos["sucursales"]:
        _upsert_sucursal(tx, documento)
    for documento in datos["farmaceuticos"]:
        _upsert_farmaceutico(tx, documento)
    for documento in datos["productos"]:
        _upsert_producto(tx, documento)
    for documento in datos["clientes"]:
        _upsert_cliente(tx, documento)
    for documento in datos["recetas"]:
        _upsert_receta(tx, documento)
    for documento in datos["ventas"]:
        _upsert_venta(tx, documento)


def proyectar_todo() -> None:
    """Rehace el grafo completo desde Mongo en una sola transacción."""
    db = base()
    datos = {
        "sucursales": list(db.sucursales.find()),
        "farmaceuticos": list(db.farmaceuticos.find()),
        "productos": list(db.productos.find()),
        "clientes": list(db.clientes.find()),
        "recetas": list(db.recetas.find()),
        "ventas": list(db.ventas.find()),
    }
    try:
        with _sesion() as sesion:
            _crear_constraints(sesion)
            sesion.execute_write(_reconstruir, datos)
    except Exception as error:
        raise GrafoPendiente("no se pudo proyectar el grafo") from error


def reconstruir() -> None:
    """Rehace el grafo completo desde Mongo."""
    proyectar_todo()


def consultar(cypher: str, **parametros) -> list[dict]:
    """Ejecuta una lectura Cypher parametrizada y devuelve filas como dicts."""
    with _sesion() as sesion:
        return sesion.execute_read(
            lambda tx: [registro.data() for registro in tx.run(cypher, **parametros)]
        )


def proyectar(funcion, *args) -> str | None:
    """Ejecuta una proyección. Si falla, devuelve el aviso y no propaga."""
    try:
        funcion(*args)
    except Exception:
        return "el grafo quedó pendiente"
    return None
