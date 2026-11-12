"""q15. Completar una venta Pendiente: descuenta stock por FEFO y actualiza la receta.

Tipo: servicio
Motor: MongoDB

Propósito: dada una venta registrada en estado Pendiente, decrementar las unidades
de cada producto en los lotes de la sucursal del farmacéutico. Se consumen primero
los lotes con vencimiento más próximo. Los lotes vencidos no se dispensan. Si el
stock vigente no alcanza, o la venta no está Pendiente, no se modifica ningún lote
ni la receta, y la venta queda como estaba.

Parámetros:
    id_venta: identificador de la venta ya registrada.

Valor de retorno:
    dict con ok, y el documento de la venta si se completó. Si el grafo no se
    pudo proyectar, aviso_grafo explica que quedó pendiente. Si se rechaza, ok
    es False y error describe el motivo.

La función descontar(id_sucursal, items) también la usa q14 antes de insertar
una venta nueva. El orden de vencimiento es {vencimiento: 1, _id: 1}.
"""

from db import base, hoy
from grafo import proyectar, upsert_venta_y_receta
from reglas import Rechazo, aplicar_receta, restaurar_receta, validar_venta


ID = "q15"
TIPO = "servicio"
DESCRIPCION = "Descuento de stock por FEFO para una venta Pendiente. Si no alcanza, no modifica ningún lote."


def reponer(aplicados: list[tuple[str, int]]) -> None:
    lotes = base().stock_lotes
    for id_lote, unidades in reversed(aplicados):
        lotes.update_one({"_id": id_lote}, {"$inc": {"unidades": unidades}})


def descontar(id_sucursal: str, items: list[dict]) -> list[dict]:
    """Arma el plan FEFO y descuenta. Si un lote ya no alcanza, repone y rechaza.

    Cada ítem vuelve con lotes: [{id_lote, unidades}]. No graba la venta.
    """
    db = base()
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

    aplicados: list[tuple[str, int]] = []
    try:
        for asignacion in planes:
            for toma in asignacion:
                resultado = db.stock_lotes.update_one(
                    {"_id": toma["id_lote"], "unidades": {"$gte": toma["unidades"]}},
                    {"$inc": {"unidades": -toma["unidades"]}},
                )
                if resultado.modified_count != 1:
                    raise Rechazo("un lote ya no alcanza")
                aplicados.append((toma["id_lote"], toma["unidades"]))
    except Rechazo:
        reponer(aplicados)
        raise

    enriquecidos = []
    for item, asignacion in zip(items, planes):
        copia = dict(item)
        copia["lotes"] = asignacion
        enriquecidos.append(copia)
    return enriquecidos


def ejecutar(id_venta: str) -> dict:
    db = base()
    venta = db.ventas.find_one({"_id": id_venta})
    if venta is None:
        return {"ok": False, "error": "la venta no existe"}
    if venta["estado"] != "Pendiente":
        return {
            "ok": False,
            "error": f"la venta está {venta['estado']}; solo se completa una Pendiente",
        }

    try:
        contexto = validar_venta(
            venta["id_cliente"],
            venta["id_farmaceutico"],
            venta["items"],
            venta.get("id_receta"),
        )
        items = descontar(contexto["sucursal"]["_id"], venta["items"])
    except Rechazo as rechazo:
        return {"ok": False, "error": rechazo.mensaje}

    anterior = None
    if contexto["receta"] is not None:
        try:
            anterior = aplicar_receta(contexto["receta"], hoy())
        except Rechazo as rechazo:
            reponer(_lotes_de(items))
            return {"ok": False, "error": rechazo.mensaje}

    fecha_reserva = venta["fecha"]
    resultado = db.ventas.update_one(
        {"_id": id_venta, "estado": "Pendiente"},
        {
            "$set": {
                "estado": "Completada",
                "fecha": hoy(),
                "fecha_registro": fecha_reserva,
                "id_sucursal": contexto["sucursal"]["_id"],
                "items": items,
            }
        },
    )
    if resultado.matched_count != 1:
        if anterior is not None:
            restaurar_receta(anterior)
        reponer(_lotes_de(items))
        return {"ok": False, "error": "la venta ya no está Pendiente"}

    documento = db.ventas.find_one({"_id": id_venta})
    receta = None
    if contexto["receta"] is not None:
        receta = db.recetas.find_one({"_id": contexto["receta"]["_id"]})
    aviso = proyectar(upsert_venta_y_receta, documento, receta)
    return _respuesta(documento, [aviso])


def _lotes_de(items: list[dict]) -> list[tuple[str, int]]:
    return [
        (toma["id_lote"], toma["unidades"])
        for item in items
        for toma in item.get("lotes", [])
    ]


def _respuesta(documento: dict, avisos: list[str | None]) -> dict:
    respuesta = {"ok": True, "documento": documento}
    if any(avisos):
        respuesta["aviso_grafo"] = "el grafo quedó pendiente"
    return respuesta
