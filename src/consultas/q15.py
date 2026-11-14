"""q15. Completar una venta Pendiente: descuenta stock por FEFO y actualiza la receta.

Tipo: servicio
Motor: MongoDB

Propósito: dada una venta registrada en estado Pendiente, decrementar las unidades
de cada producto en los lotes de la sucursal del farmacéutico. Se consumen primero
los lotes con vencimiento más próximo. Los lotes vencidos no se dispensan. Si el
stock vigente no alcanza, o la venta no está Pendiente, no se modifica ningún lote
ni la receta, y la venta queda como estaba. Los cambios se confirman en una
única transacción MongoDB; el grafo se proyecta después del commit.

Parámetros:
    id_venta: identificador de la venta ya registrada.

Valor de retorno:
    dict con ok, y el documento de la venta si se completó. Si el grafo no se
    pudo proyectar, aviso_grafo explica que quedó pendiente. Si se rechaza, ok
    es False y error describe el motivo.

La función descontar(id_sucursal, items) también la usa q14 antes de insertar
una venta nueva. El orden de vencimiento es {vencimiento: 1, _id: 1}.
"""

from pymongo.errors import PyMongoError

from db import base, hoy
from grafo import proyectar, upsert_venta_y_receta
from reglas import Rechazo, aplicar_receta, validar_texto, validar_venta


ID = "q15"
TIPO = "servicio"
DESCRIPCION = "Descuento de stock por FEFO para una venta Pendiente. Si no alcanza, no modifica ningún lote."


def descontar(id_sucursal: str, items: list[dict], *, db, session) -> list[dict]:
    """Arma el plan FEFO y descuenta dentro de la transacción del llamador.

    Cada ítem vuelve con lotes: [{id_lote, unidades}]. No graba la venta.
    """
    fecha = hoy()
    planes: list[list[dict]] = []
    vistos: dict[str, int] = {}

    for item in items:
        falta = item["cantidad"]
        asignacion: list[dict] = []
        cursor = db.stock_lotes.find(
            {
                "id_producto": item["id_producto"],
                "id_sucursal": id_sucursal,
                "vencimiento": {"$gte": fecha},
            },
            sort=[("vencimiento", 1), ("_id", 1)],
            session=session,
        )
        for lote in cursor:
            if falta == 0:
                break
            disponible = vistos.get(lote["_id"], lote["unidades"])
            tomar = min(falta, disponible)
            if tomar <= 0:
                continue
            asignacion.append({"id_lote": lote["_id"], "unidades": tomar})
            vistos[lote["_id"]] = disponible - tomar
            falta -= tomar
        if falta:
            raise Rechazo(
                f"no hay stock vigente de {item['id_producto']} en {id_sucursal}"
            )
        planes.append(asignacion)

    for asignacion in planes:
        for toma in asignacion:
            resultado = db.stock_lotes.update_one(
                {"_id": toma["id_lote"], "unidades": {"$gte": toma["unidades"]}},
                {"$inc": {"unidades": -toma["unidades"]}},
                session=session,
            )
            if resultado.modified_count != 1:
                raise Rechazo("un lote ya no alcanza")

    enriquecidos = []
    for item, asignacion in zip(items, planes):
        copia = dict(item)
        copia["lotes"] = asignacion
        enriquecidos.append(copia)
    return enriquecidos


def ejecutar(id_venta: str) -> dict:
    try:
        validar_texto(id_venta, "id_venta")
    except Rechazo as rechazo:
        return {"ok": False, "error": rechazo.mensaje}
    db = base()
    fecha = hoy()

    def completar(session):
        venta = db.ventas.find_one({"_id": id_venta}, session=session)
        if venta is None:
            raise Rechazo("la venta no existe")
        if venta["estado"] != "Pendiente":
            raise Rechazo(f"la venta está {venta['estado']}; solo se completa una Pendiente")
        contexto = validar_venta(venta["id_cliente"], venta["id_farmaceutico"],
                                 venta["items"], venta.get("id_receta"), db=db, session=session)
        items = descontar(contexto["sucursal"]["_id"], venta["items"], db=db, session=session)
        if contexto["receta"] is not None:
            aplicar_receta(contexto["receta"], fecha, db=db, session=session)
        resultado = db.ventas.update_one(
            {"_id": id_venta, "estado": "Pendiente"},
            {"$set": {"estado": "Completada", "fecha": fecha,
                      "fecha_registro": venta["fecha"],
                      "id_sucursal": contexto["sucursal"]["_id"], "items": items},
             "$inc": {"_version": 1}},
            session=session,
        )
        if resultado.matched_count != 1:
            raise Rechazo("la venta ya no está Pendiente")
        documento = db.ventas.find_one({"_id": id_venta}, session=session)
        receta = (db.recetas.find_one({"_id": contexto["receta"]["_id"]}, session=session)
                  if contexto["receta"] is not None else None)
        return documento, receta

    try:
        with db.client.start_session() as session:
            documento, receta = session.with_transaction(completar)
    except Rechazo as rechazo:
        return {"ok": False, "error": rechazo.mensaje}
    except PyMongoError:
        return {"ok": False, "error": "no se pudo confirmar la venta"}

    aviso = proyectar(upsert_venta_y_receta, documento, receta)
    return _respuesta(documento, [aviso])


def _respuesta(documento: dict, avisos: list[str | None]) -> dict:
    respuesta = {"ok": True, "documento": documento}
    if any(avisos):
        respuesta["aviso_grafo"] = "el grafo quedó pendiente"
    return respuesta
