"""Proyección a Neo4j y consultas Cypher de las relaciones del TPO.

Mongo es la fuente de verdad. La carga completa llama a proyectar_todo, que crea
los constraints, vacía el grafo y lo reconstruye desde Mongo en una transacción.
Las escrituras individuales de q13, q14 y q15 llaman a upsert_cliente,
upsert_venta_y_receta y las proyecciones puntuales, que reemplazan las relaciones
viejas para no duplicar ni conservar vínculos obsoletos.

Cada cambio confirmado en Mongo queda marcado hasta que Neo4j lo confirma.
Si una proyección falla, proyectar devuelve el aviso y conserva el pendiente.
consultar recupera los pendientes antes de leer; si no puede, rechaza la lectura.
La carga conserva también el estado de su reconstrucción completa.
"""

from contextlib import contextmanager
from datetime import date, datetime

from bson import ObjectId
from neo4j import GraphDatabase
from neo4j.exceptions import DriverError, Neo4jError
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from db import NEO4J_URI, base

ETIQUETAS = ("Cliente", "Sucursal", "Farmaceutico", "Producto", "Receta", "Venta")


class GrafoPendiente(Exception):
    """Neo4j no está disponible o la proyección no se pudo aplicar."""


class ReferenciaGrafo(Exception):
    """Una referencia del documento no existe en el grafo."""


@contextmanager
def _driver():
    driver = GraphDatabase.driver(NEO4J_URI)
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


def _exigir(tx, etiqueta: str, ids: list[str]) -> None:
    """Falla si alguna de las referencias no existe en el grafo."""
    if etiqueta not in ETIQUETAS:
        raise ValueError(f"etiqueta desconocida: {etiqueta}")
    unicos = list(dict.fromkeys(ids))
    if not unicos:
        return
    filas = tx.run(
        f"MATCH (n:{etiqueta}) WHERE n.id IN $ids RETURN n.id AS id",
        ids=unicos,
    )
    faltan = set(unicos) - {fila["id"] for fila in filas}
    if faltan:
        raise ReferenciaGrafo(f"{etiqueta} inexistente en el grafo: {sorted(faltan)}")


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
    _exigir(tx, "Sucursal", [documento["id_sucursal"]])
    tx.run(
        """
        MERGE (f:Farmaceutico {id: $id})
        SET f.nombre = $nombre,
            f.apellido = $apellido,
            f.matricula = $matricula,
            f.cargo = $cargo,
            f.activo = $activo
        WITH f
        OPTIONAL MATCH (f)-[vieja:TRABAJA_EN]->()
        DELETE vieja
        WITH f
        MATCH (s:Sucursal {id: $id_sucursal})
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


def _aceptar_version(tx, etiqueta: str, documento: dict) -> bool:
    # Leer y escribir la misma propiedad toma el lock antes de comparar versiones.
    return tx.run(
        f"""
        MERGE (n:{etiqueta} {{id: $id}})
        SET n._version = coalesce(n._version, 0)
        WITH n
        WHERE n._version <= $version
        SET n._version = $version
        RETURN n.id AS id
        """,
        id=documento.get("_id") or documento["id_venta"],
        version=documento.get("_version", 0),
    ).single() is not None


def _upsert_cliente(tx, documento: dict) -> None:
    if not _aceptar_version(tx, "Cliente", documento):
        return
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
    _exigir(tx, "Cliente", [documento["id_cliente"]])
    if not _aceptar_version(tx, "Receta", documento):
        return
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
        OPTIONAL MATCH (r)-[vieja:PRESCRIPTA_A]->()
        DELETE vieja
        WITH r
        MATCH (c:Cliente {id: $id_cliente})
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


def _items_detalle(items: list[dict]) -> list[dict]:
    """Conserva una relación por ítem, sin perder precios distintos."""
    resultado = []
    for indice, item in enumerate(items):
        id_detalle = item.get("id_detalle")
        if id_detalle is None:
            id_detalle = f"{item['id_producto']}#{indice}"
        resultado.append(
            {
                "id_detalle": id_detalle,
                "id_producto": item["id_producto"],
                "cantidad": item["cantidad"],
                "precio_unit": item["precio_unit"],
            }
        )
    return resultado


def _upsert_venta(tx, documento: dict) -> None:
    id_venta = documento.get("_id") or documento["id_venta"]
    id_cliente = documento["id_cliente"]
    id_farmaceutico = documento["id_farmaceutico"]
    id_receta = documento.get("id_receta")
    id_sucursal = documento.get("id_sucursal")
    items = _items_detalle(documento.get("items", []))
    if not _aceptar_version(tx, "Venta", documento):
        return

    _exigir(tx, "Cliente", [id_cliente])
    _exigir(tx, "Farmaceutico", [id_farmaceutico])
    if id_receta:
        _exigir(tx, "Receta", [id_receta])
    _exigir(tx, "Producto", [item["id_producto"] for item in items])
    if id_sucursal:
        _exigir(tx, "Sucursal", [id_sucursal])

    tx.run(
        """
        MERGE (v:Venta {id: $id})
        SET v.fecha = $fecha,
            v.tipo = $tipo,
            v.medio_pago = $medio_pago,
            v.total = $total,
            v.estado = $estado,
            v.fecha_registro = $fecha_registro,
            v.id_sucursal = null
        WITH v
        OPTIONAL MATCH (v)<-[entrada:REALIZO|ATENDIO]-()
        DELETE entrada
        WITH v
        OPTIONAL MATCH (v)-[salida:CON_RECETA|INCLUYE|EN_SUCURSAL]->()
        DELETE salida
        """,
        id=id_venta,
        fecha=_fecha(documento["fecha"]),
        tipo=documento["tipo"],
        medio_pago=documento["medio_pago"],
        total=documento["total"],
        estado=documento["estado"],
        fecha_registro=_fecha(documento.get("fecha_registro")),
    ).consume()

    tx.run(
        """
        MATCH (v:Venta {id: $id})
        MATCH (c:Cliente {id: $id_cliente})
        MERGE (c)-[:REALIZO]->(v)
        WITH v
        MATCH (f:Farmaceutico {id: $id_farmaceutico})
        MERGE (f)-[:ATENDIO]->(v)
        """,
        id=id_venta,
        id_cliente=id_cliente,
        id_farmaceutico=id_farmaceutico,
    ).consume()

    if id_sucursal:
        tx.run(
            """
            MATCH (v:Venta {id: $id})
            MATCH (s:Sucursal {id: $id_sucursal})
            MERGE (v)-[:EN_SUCURSAL]->(s)
            SET v.id_sucursal = s.id
            """,
            id=id_venta,
            id_sucursal=id_sucursal,
        ).consume()
    else:
        registro = tx.run(
            """
            MATCH (v:Venta {id: $id})
            MATCH (f:Farmaceutico {id: $id_farmaceutico})-[:TRABAJA_EN]->(s:Sucursal)
            MERGE (v)-[:EN_SUCURSAL]->(s)
            SET v.id_sucursal = s.id
            RETURN s.id AS id
            LIMIT 1
            """,
            id=id_venta,
            id_farmaceutico=id_farmaceutico,
        ).single()
        if registro is None:
            raise ReferenciaGrafo(
                f"Farmaceutico {id_farmaceutico} sin sucursal en el grafo"
            )

    if id_receta:
        tx.run(
            """
            MATCH (v:Venta {id: $id_venta})
            MATCH (r:Receta {id: $id_receta})
            MERGE (v)-[:CON_RECETA]->(r)
            """,
            id_venta=id_venta,
            id_receta=id_receta,
        ).consume()

    if items:
        tx.run(
            """
            MATCH (v:Venta {id: $id_venta})
            UNWIND $items AS item
            MATCH (p:Producto {id: item.id_producto})
            MERGE (v)-[i:INCLUYE {id_detalle: item.id_detalle}]->(p)
            SET i.cantidad = item.cantidad,
                i.precio_unit = item.precio_unit
            """,
            id_venta=id_venta,
            items=items,
        ).consume()


_PROYECCIONES = {
    "sucursales": _upsert_sucursal,
    "farmaceuticos": _upsert_farmaceutico,
    "productos": _upsert_producto,
    "clientes": _upsert_cliente,
    "recetas": _upsert_receta,
    "ventas": _upsert_venta,
}
COLECCIONES_PENDIENTES = ("clientes", "recetas", "ventas")


def _limpiar_pendiente(nombre: str, documento: dict) -> None:
    # Una proyección vieja no confirma la actualización que llegó después.
    version = documento.get("_version", 0)
    filtro = {"_id": documento["_id"], "grafo_pendiente": True}
    if version == 0:
        filtro["$or"] = [{"_version": 0}, {"_version": {"$exists": False}}]
    else:
        filtro["_version"] = version
    base()[nombre].update_one(filtro, {"$set": {"grafo_pendiente": False}})


def _proyectar_datos(tx, datos: dict[str, list[dict]]) -> None:
    for nombre, funcion in _PROYECCIONES.items():
        for documento in datos.get(nombre, []):
            funcion(tx, documento)


def recuperar_pendientes() -> None:
    """Reintenta lo confirmado en Mongo y aún no confirmado en el grafo.

    Si entran cambios nuevos durante el intento, la lectura se rechaza para no
    devolver datos que sabemos atrasados. El siguiente intento toma sus versiones.
    """
    try:
        db = base()
        if db["_estado_grafo"].find_one({"_id": "reconstruccion"}):
            proyectar_todo()
        datos = {nombre: list(db[nombre].find({"grafo_pendiente": True}))
                 for nombre in COLECCIONES_PENDIENTES}
        if not any(datos.values()):
            if db["_estado_grafo"].find_one({"_id": "reconstruccion"}):
                raise GrafoPendiente("hay una reconstrucción nueva pendiente")
            return
        with _sesion() as sesion:
            _crear_constraints(sesion)
            sesion.execute_write(_proyectar_datos, datos)
        for nombre, documentos in datos.items():
            for documento in documentos:
                _limpiar_pendiente(nombre, documento)
        if db["_estado_grafo"].find_one({"_id": "reconstruccion"}) or any(
               db[nombre].find_one({"grafo_pendiente": True}, {"_id": 1})
               for nombre in COLECCIONES_PENDIENTES):
            raise GrafoPendiente("hay cambios nuevos pendientes de proyectar")
    except (ReferenciaGrafo, Neo4jError, DriverError, OSError, PyMongoError) as error:
        raise GrafoPendiente("no se pudo recuperar el grafo pendiente") from error


def upsert_cliente(documento: dict) -> None:
    """Crea o actualiza el nodo del cliente."""
    with _sesion() as sesion:
        sesion.execute_write(_upsert_cliente, documento)
    _limpiar_pendiente("clientes", documento)


def upsert_venta(documento: dict) -> None:
    """Crea o actualiza la venta y sus relaciones."""
    with _sesion() as sesion:
        sesion.execute_write(_upsert_venta, documento)
    _limpiar_pendiente("ventas", documento)


def upsert_receta(documento: dict) -> None:
    """Crea o actualiza la receta y su relación con el cliente."""
    with _sesion() as sesion:
        sesion.execute_write(_upsert_receta, documento)
    _limpiar_pendiente("recetas", documento)


def upsert_venta_y_receta(documento: dict, receta: dict | None = None) -> None:
    """Proyecta la venta y su receta en una sola transacción."""

    def escribir(tx) -> None:
        if receta is not None:
            _upsert_receta(tx, receta)
        _upsert_venta(tx, documento)

    with _sesion() as sesion:
        sesion.execute_write(escribir)
    if receta is not None:
        _limpiar_pendiente("recetas", receta)
    _limpiar_pendiente("ventas", documento)


def _reconstruir(tx, datos: dict[str, list[dict]]) -> None:
    tx.run("MATCH (n) DETACH DELETE n").consume()
    _proyectar_datos(tx, datos)


def proyectar_todo() -> None:
    """Rehace el grafo completo desde Mongo en una sola transacción.

    La lectura de las colecciones no es una foto transaccional: la carga debe
    ejecutarse sin escrituras concurrentes en Mongo.
    """
    db = base()
    reconstruccion = db["_estado_grafo"].find_one_and_update(
        {"_id": "reconstruccion"},
        {"$setOnInsert": {"generacion": ObjectId(), "carga_lista": True}},
        upsert=True, return_document=ReturnDocument.AFTER,
    )
    if not reconstruccion.get("carga_lista"):
        raise GrafoPendiente("carga incompleta: repetir scripts/cargar.py")
    farmaceuticos = list(db.farmaceuticos.find())
    sucursal_de = {f["_id"]: f["id_sucursal"] for f in farmaceuticos}
    ventas = list(db.ventas.find())
    for venta in ventas:
        if not venta.get("id_sucursal"):
            venta["id_sucursal"] = sucursal_de.get(venta["id_farmaceutico"])
    datos = {
        "sucursales": list(db.sucursales.find()),
        "farmaceuticos": farmaceuticos,
        "productos": list(db.productos.find()),
        "clientes": list(db.clientes.find()),
        "recetas": list(db.recetas.find()),
        "ventas": ventas,
    }
    try:
        with _sesion() as sesion:
            _crear_constraints(sesion)
            sesion.execute_write(_reconstruir, datos)
        # El reemplazo pudo borrar una proyección confirmada después de la foto.
        for nombre in COLECCIONES_PENDIENTES:
            db[nombre].update_many({}, {"$set": {"grafo_pendiente": True}})
        for nombre in COLECCIONES_PENDIENTES:
            for documento in datos[nombre]:
                _limpiar_pendiente(nombre, documento)
        if reconstruccion is not None:
            db["_estado_grafo"].delete_one(reconstruccion)
    except Exception as error:
        raise GrafoPendiente("no se pudo proyectar el grafo") from error


def reconstruir() -> None:
    """Rehace el grafo completo desde Mongo."""
    proyectar_todo()


def consultar(cypher: str, **parametros) -> list[dict]:
    """Ejecuta una lectura Cypher parametrizada y devuelve filas como dicts.

    Si Neo4j no está disponible, levanta GrafoPendiente con un mensaje claro.
    """
    try:
        recuperar_pendientes()
        with _sesion() as sesion:
            return sesion.execute_read(
                lambda tx: [
                    registro.data() for registro in tx.run(cypher, **parametros)
                ]
            )
    except (Neo4jError, DriverError, OSError) as error:
        raise GrafoPendiente("no se pudo consultar el grafo") from error


def proyectar(funcion, *args) -> str | None:
    """Ejecuta una proyección. Si falla, devuelve el aviso y no propaga."""
    try:
        funcion(*args)
    except (GrafoPendiente, ReferenciaGrafo, Neo4jError, DriverError, OSError, PyMongoError):
        return "el grafo quedó pendiente"
    return None
