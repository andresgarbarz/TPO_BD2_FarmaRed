"""q14. Registro de una venta Completada, con validaciones y actualización de la receta.

Tipo: servicio
Motor: MongoDB

Propósito: registrar una venta nueva en estado Completada, con su cabecera y sus
ítems. Valida cliente, farmacéutico, sucursal y productos. Si hay productos bajo
receta, exige una receta vigente del mismo cliente. El precio de cada ítem es el
del catálogo en ese momento y el total es la suma. Lotes, receta y venta se
confirman en una única transacción MongoDB. Un rechazo o error aborta todos
los cambios; la proyección del grafo se hace después del commit.

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

from pymongo.errors import PyMongoError

from db import base, hoy
from grafo import proyectar, upsert_venta_y_receta
from ids import preparar, reservar
from reglas import MEDIOS, Rechazo, aplicar_receta, validar_entrada_venta, validar_venta

from .q15 import descontar


ID = "q14"
TIPO = "servicio"
DESCRIPCION = "Registro de una venta Completada, con validaciones y actualización de la receta."


def ejecutar(id_cliente: str, id_farmaceutico: str, items: list[dict], medio_pago: str, id_receta: str | None = None) -> dict:
    if not isinstance(medio_pago, str) or medio_pago not in MEDIOS:
        return {"ok": False, "error": "el medio de pago no es uno de los previstos"}

    try:
        validar_entrada_venta(id_cliente, id_farmaceutico, items, id_receta)
    except Rechazo as rechazo:
        return {"ok": False, "error": rechazo.mensaje}

    db = base()
    fecha = hoy()

    def registrar(session):
        contexto = validar_venta(id_cliente, id_farmaceutico, items, id_receta,
                                 db=db, session=session)
        armados = [{"id_producto": item["id_producto"], "cantidad": item["cantidad"],
                    "precio_unit": contexto["productos"][item["id_producto"]]["precio_unit"]}
                   for item in items]
        armados = descontar(contexto["sucursal"]["_id"], armados, db=db, session=session)
        if contexto["receta"] is not None:
            aplicar_receta(contexto["receta"], fecha, db=db, session=session)
        siguiente = reservar(db, "D", len(armados), session=session)
        for item in armados:
            item["id_detalle"] = f"D{siguiente:03d}"
            siguiente += 1
        documento = {
            "id_cliente": id_cliente,
            "id_farmaceutico": id_farmaceutico,
            "id_receta": id_receta,
            "id_sucursal": contexto["sucursal"]["_id"],
            "fecha": fecha,
            "tipo": "Con receta" if contexto["pide_receta"] else "Venta libre",
            "medio_pago": medio_pago,
            "total": sum(item["cantidad"] * item["precio_unit"] for item in armados),
            "estado": "Completada",
            "_version": 1,
            "grafo_pendiente": True,
            "items": armados,
        }
        _insertar_venta(documento, db=db, session=session)
        receta = db.recetas.find_one({"_id": id_receta}, session=session) if id_receta else None
        return documento, receta

    try:
        preparar(db, "V", "D")
        with db.client.start_session() as session:
            documento, receta = session.with_transaction(registrar)
    except Rechazo as rechazo:
        return {"ok": False, "error": rechazo.mensaje}
    except PyMongoError:
        return {"ok": False, "error": "no se pudo confirmar la venta"}

    aviso = proyectar(upsert_venta_y_receta, documento, receta)
    respuesta = {"ok": True, "documento": documento}
    if aviso:
        respuesta["aviso_grafo"] = aviso
    return respuesta


def _insertar_venta(documento: dict, *, db, session) -> None:
    nuevo = f"V{reservar(db, 'V', session=session):03d}"
    documento["_id"] = documento["id_venta"] = nuevo
    db.ventas.insert_one(dict(documento), session=session)
