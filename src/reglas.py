"""Validaciones compartidas por el registro y la completitud de una venta."""

from datetime import timedelta

from db import base, hoy

OBRAS = ("OSDE", "Swiss Medical", "PAMI", "IOMA", "Galeno", "Sin cobertura")
MEDIOS = ("Efectivo", "Débito", "Crédito", "Transferencia", "Obra social")
BAJO_RECETA = ("Bajo receta", "Bajo receta archivada")


class Rechazo(Exception):
    def __init__(self, mensaje: str):
        super().__init__(mensaje)
        self.mensaje = mensaje


def validar_texto(valor, campo: str) -> None:
    if not isinstance(valor, str) or not valor.strip():
        raise Rechazo(f"{campo} tiene que ser un texto no vacío")


def validar_cobertura(obra_social: str, nro_afiliado: str | None) -> None:
    validar_texto(obra_social, "obra_social")
    if nro_afiliado not in (None, ""):
        validar_texto(nro_afiliado, "nro_afiliado")
    if obra_social not in OBRAS:
        raise Rechazo("la obra social no es una de las previstas")
    vacio = nro_afiliado is None or nro_afiliado == ""
    if obra_social == "Sin cobertura" and not vacio:
        raise Rechazo("Sin cobertura no lleva número de afiliado")
    if obra_social != "Sin cobertura" and vacio:
        raise Rechazo("la obra social exige número de afiliado")


def validar_venta(id_cliente: str, id_farmaceutico: str, items: list[dict], id_receta: str | None, *, db=None, session=None):
    """Revisa cliente, farmacéutico, sucursal, productos y receta. No escribe."""
    validar_texto(id_cliente, "id_cliente")
    validar_texto(id_farmaceutico, "id_farmaceutico")
    if id_receta is not None:
        validar_texto(id_receta, "id_receta")
    if not isinstance(items, list):
        raise Rechazo("items tiene que ser una lista")
    if not items:
        raise Rechazo("la venta no tiene ítems")
    for item in items:
        if not isinstance(item, dict) or "id_producto" not in item or "cantidad" not in item:
            raise Rechazo("cada ítem necesita id_producto y cantidad")
        validar_texto(item["id_producto"], "id_producto")
        if type(item["cantidad"]) is not int or item["cantidad"] <= 0:
            raise Rechazo("la cantidad tiene que ser un entero mayor a cero")

    if db is None:
        db = base()
    cliente = db.clientes.find_one({"_id": id_cliente}, session=session)
    if cliente is None:
        raise Rechazo("el cliente no existe")
    if not cliente["activo"]:
        raise Rechazo("el cliente no está activo")

    farmaceutico = db.farmaceuticos.find_one({"_id": id_farmaceutico}, session=session)
    if farmaceutico is None:
        raise Rechazo("el farmacéutico no existe")
    if not farmaceutico["activo"]:
        raise Rechazo("el farmacéutico no está activo")

    sucursal = db.sucursales.find_one({"_id": farmaceutico["id_sucursal"]}, session=session)
    if sucursal is None or sucursal["tipo"] != "Farmacia":
        raise Rechazo("el farmacéutico no pertenece a una sucursal de tipo Farmacia")

    productos = {}
    for item in items:
        producto = db.productos.find_one({"_id": item["id_producto"]}, session=session)
        if producto is None:
            raise Rechazo(f"el producto {item['id_producto']} no existe")
        if not producto["activo"]:
            raise Rechazo(f"el producto {item['id_producto']} no está activo")
        productos[item["id_producto"]] = producto

    pide_receta = any(productos[item["id_producto"]]["condicion_venta"] in BAJO_RECETA for item in items)
    receta = None
    if id_receta:
        receta = db.recetas.find_one({"_id": id_receta}, session=session)
        if receta is None:
            raise Rechazo("la receta no existe")
        if receta["id_cliente"] != id_cliente:
            raise Rechazo("la receta no es del mismo cliente")
        if receta["estado"] != "Vigente":
            raise Rechazo("la receta no está vigente")
        if receta["dispensas_realizadas"] >= receta["dispensas_autorizadas"]:
            raise Rechazo("la receta no tiene dispensas disponibles")
    elif pide_receta:
        raise Rechazo("el producto bajo receta exige una receta vigente del mismo cliente")

    return {
        "cliente": cliente,
        "farmaceutico": farmaceutico,
        "sucursal": sucursal,
        "productos": productos,
        "receta": receta,
        "pide_receta": pide_receta,
    }


def estado_receta(receta: dict, fecha) -> dict:
    """Próximo estado de la receta después de una dispensa."""
    hechas = receta["dispensas_realizadas"] + 1
    if receta["tipo"] == "Tratamiento prolongado" and hechas < receta["dispensas_autorizadas"]:
        return {
            "dispensas_realizadas": hechas,
            "proxima_dispensa": fecha + timedelta(days=30),
            "estado": "Vigente",
        }
    return {
        "dispensas_realizadas": hechas,
        "proxima_dispensa": None,
        "estado": "Completada",
    }


def aplicar_receta(receta: dict, fecha, *, db, session) -> None:
    """Actualiza la receta dentro de la misma transacción que la venta y el stock."""
    nuevo = estado_receta(receta, fecha)
    resultado = db.recetas.update_one(
        {"_id": receta["_id"], "dispensas_realizadas": receta["dispensas_realizadas"]},
        {"$set": nuevo},
        session=session,
    )
    if resultado.matched_count != 1:
        raise Rechazo("la receta cambió mientras se registraba la venta")


def fecha_dispensa():
    return hoy()
