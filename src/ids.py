"""Correlativos globales C/V/D: la reserva se hace con un incremento atómico."""

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError


def _maximo(valores, prefijo: str) -> int:
    maximo = max((int(valor[len(prefijo):]) for valor in valores
                  if isinstance(valor, str) and valor.startswith(prefijo)
                  and valor[len(prefijo):].isdecimal()), default=0)
    if maximo >= 2 ** 63 - 1:
        raise ValueError("la secuencia excede el rango de enteros BSON")
    return maximo


def desde_documentos(documentos: dict) -> list[dict]:
    """Prepara las secuencias antes del primer borrado de la carga."""
    valores = {
        "C": (d["_id"] for d in documentos["clientes"]),
        "V": (d["_id"] for d in documentos["ventas"]),
        "D": (i["id_detalle"] for d in documentos["ventas"] for i in d["items"]),
    }
    return [{"_id": prefijo, "ultimo": _maximo(ids, prefijo)}
            for prefijo, ids in valores.items()]


def iniciar(db, secuencias: list[dict]) -> None:
    """La carga de reinicio reemplaza también las secuencias desde sus CSV."""
    db.contadores.drop()
    db.contadores.insert_many(secuencias)


def preparar(db, *prefijos: str) -> None:
    """Migra una base sin contadores antes de abrir la transacción de venta."""
    for prefijo in prefijos:
        if db.contadores.find_one({"_id": prefijo}) is not None:
            continue
        if prefijo == "C":
            valores = (d["_id"] for d in db.clientes.find({}, {"_id": 1}))
        elif prefijo == "V":
            valores = (d["_id"] for d in db.ventas.find({}, {"_id": 1}))
        elif prefijo == "D":
            valores = (i["id_detalle"] for d in db.ventas.find({}, {"items.id_detalle": 1})
                       for i in d.get("items", []))
        else:
            raise ValueError("prefijo de id desconocido")
        try:
            db.contadores.update_one({"_id": prefijo},
                                     {"$setOnInsert": {"ultimo": _maximo(valores, prefijo)}},
                                     upsert=True)
        except DuplicateKeyError:
            # Otra llamada terminó la misma inicialización antes de este upsert.
            pass


def reservar(db, prefijo: str, cantidad: int = 1, *, session=None) -> int:
    """Devuelve el primer número de un bloque reservado; no vuelve a leer máximos."""
    contador = db.contadores.find_one_and_update(
        {"_id": prefijo}, {"$inc": {"ultimo": cantidad}},
        return_document=ReturnDocument.AFTER, session=session,
    )
    if contador is None:
        raise RuntimeError("falta inicializar los contadores")
    return contador["ultimo"] - cantidad + 1
