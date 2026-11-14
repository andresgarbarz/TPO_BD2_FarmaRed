"""q14. Registro de una venta Completada, con validaciones y actualización de la receta.

Tipo: servicio
Motor: MongoDB

Propósito: registrar una venta nueva en estado Completada, con su cabecera y sus
ítems. Valida cliente, farmacéutico, sucursal y productos. Si hay productos bajo
receta, exige una receta vigente del mismo cliente. El precio de cada ítem es el
del catálogo en ese momento y el total es la suma. El stock se descuenta antes de
insertar, con la función descontar de q15. Si el descuento o la receta fallan, no
queda la venta y los lotes vuelven a su estado anterior.

Parámetros:
    id_cliente: cliente que compra. Tiene que existir y estar activo.
    id_farmaceutico: farmacéutico que atiende. Activo y de una sucursal Farmacia.
    items: lista de dict con id_producto y cantidad.
    medio_pago: Efectivo, Débito, Crédito, Transferencia u Obra social.
    id_receta: obligatoria si algún producto es bajo receta. Si no, puede omitirse.

No recibe la fecha: usa la fecha del sistema en Argentina.

Valor de retorno:
    dict con ok y el documento de la venta. Si el grafo no se pudo proyectar,
    aviso_grafo indica que quedó pendiente. Si se rechaza, ok es False y error
    describe el motivo. El id de la venta y el de cada ítem se generan.
"""

from pymongo.errors import DuplicateKeyError

from db import base, hoy
from grafo import proyectar, upsert_venta_y_receta
from reglas import MEDIOS, Rechazo, aplicar_receta, restaurar_receta, validar_venta

from .q15 import descontar, reponer


ID = "q14"
TIPO = "servicio"
DESCRIPCION = "Registro de una venta Completada, con validaciones y actualización de la receta."


def ejecutar(id_cliente: str, id_farmaceutico: str, items: list[dict], medio_pago: str, id_receta: str | None = None) -> dict:
    if not isinstance(medio_pago, str) or medio_pago not in MEDIOS:
        return {"ok": False, "error": "el medio de pago no es uno de los previstos"}

    try:
        contexto = validar_venta(id_cliente, id_farmaceutico, items, id_receta)
    except Rechazo as rechazo:
        return {"ok": False, "error": rechazo.mensaje}

    armados = []
    for item in items:
        producto = contexto["productos"][item["id_producto"]]
        armados.append(
            {
                "id_producto": item["id_producto"],
                "cantidad": item["cantidad"],
                "precio_unit": producto["precio_unit"],
            }
        )

    try:
        armados = descontar(contexto["sucursal"]["_id"], armados)
    except Rechazo as rechazo:
        return {"ok": False, "error": rechazo.mensaje}

    anterior = None
    if contexto["receta"] is not None:
        try:
            anterior = aplicar_receta(contexto["receta"], hoy())
        except Rechazo as rechazo:
            reponer(_lotes(armados))
            return {"ok": False, "error": rechazo.mensaje}

    siguiente = _maximo(base().ventas, "D", "items.id_detalle") + 1
    for item in armados:
        item["id_detalle"] = f"D{siguiente:03d}"
        siguiente += 1
    total = sum(item["cantidad"] * item["precio_unit"] for item in armados)
    documento = {
        "id_cliente": id_cliente,
        "id_farmaceutico": id_farmaceutico,
        "id_receta": id_receta,
        "id_sucursal": contexto["sucursal"]["_id"],
        "fecha": hoy(),
        "tipo": "Con receta" if contexto["pide_receta"] else "Venta libre",
        "medio_pago": medio_pago,
        "total": total,
        "estado": "Completada",
        "items": armados,
    }

    try:
        _insertar_venta(documento)
    except RuntimeError:
        if anterior is not None:
            restaurar_receta(anterior)
        reponer(_lotes(armados))
        return {"ok": False, "error": "no se pudo asignar un id de venta"}

    receta = None
    if contexto["receta"] is not None:
        receta = base().recetas.find_one({"_id": contexto["receta"]["_id"]})
    aviso = proyectar(upsert_venta_y_receta, documento, receta)
    respuesta = {"ok": True, "documento": documento}
    if aviso:
        respuesta["aviso_grafo"] = aviso
    return respuesta


def _lotes(items: list[dict]) -> list[tuple[str, int]]:
    return [
        (toma["id_lote"], toma["unidades"])
        for item in items
        for toma in item.get("lotes", [])
    ]


def _insertar_venta(documento: dict) -> None:
    ventas = base().ventas
    for _ in range(5):
        nuevo = f"V{_maximo(ventas, 'V', '_id') + 1:03d}"
        documento["_id"] = nuevo
        documento["id_venta"] = nuevo
        try:
            ventas.insert_one(dict(documento))
            return
        except DuplicateKeyError:
            continue
    raise RuntimeError("id de venta")


def _maximo(ventas, prefijo: str, campo: str) -> int:
    maximo = 0
    if campo == "_id":
        valores = (doc["_id"] for doc in ventas.find({}, {"_id": 1}))
    else:
        valores = (
            item.get("id_detalle")
            for doc in ventas.find({}, {"items.id_detalle": 1})
            for item in doc.get("items", [])
        )
    for valor in valores:
        if isinstance(valor, str) and valor.startswith(prefijo):
            try:
                maximo = max(maximo, int(valor[len(prefijo):]))
            except ValueError:
                continue
    return maximo
