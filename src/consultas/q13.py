"""q13. ABM de clientes: alta con DNI único, modificación de contacto y cobertura, y baja lógica.

Tipo: servicio
Motor: MongoDB

Propósito: alta de un cliente, cambio de sus datos de contacto y cobertura, o baja
lógica. El alta valida que el DNI no exista, aunque el cliente anterior esté de
baja, y que la cobertura sea coherente: obra social de la lista, y número de
afiliado vacío solo si la obra es Sin cobertura. La baja pone activo en false y
no borra el documento. Después se proyecta el cliente en el grafo.

Parámetros:
    operacion: "alta", "modificar" o "baja".
    alta: nombre, apellido, dni, email, telefono, ciudad, provincia, obra_social
        y, si corresponde, nro_afiliado.
    modificar: id_cliente y solo email, telefono, ciudad, provincia, obra_social
        y nro_afiliado. Ciudad y provincia se tratan como contacto.
    baja: id_cliente.

Valor de retorno:
    dict con ok y el documento del cliente. Si el grafo no se pudo proyectar,
    aviso_grafo indica que quedó pendiente. Si se rechaza, ok es False y error
    describe el motivo. El id del alta lo genera el servicio.
"""

from pymongo.errors import DuplicateKeyError

from db import base
from grafo import proyectar, upsert_cliente
from reglas import Rechazo, validar_cobertura, validar_texto


ID = "q13"
TIPO = "servicio"
DESCRIPCION = "ABM de clientes: alta con DNI único, modificación de contacto y cobertura, y baja lógica."

CONTACTO = ("email", "telefono", "ciudad", "provincia", "obra_social", "nro_afiliado")
ALTA = ("nombre", "apellido", "dni", "email", "telefono", "ciudad", "provincia", "obra_social")


def ejecutar(operacion: str, **datos) -> dict:
    if operacion == "alta":
        return alta(**datos)
    if operacion == "modificar":
        try:
            id_cliente = datos.pop("id_cliente")
        except KeyError:
            return {"ok": False, "error": "falta id_cliente"}
        return modificar(id_cliente, **datos)
    if operacion == "baja":
        try:
            id_cliente = datos["id_cliente"]
        except KeyError:
            return {"ok": False, "error": "falta id_cliente"}
        return baja(id_cliente)
    return {"ok": False, "error": "la operación tiene que ser alta, modificar o baja"}


def alta(**datos) -> dict:
    faltan = [campo for campo in ALTA if campo not in datos or datos[campo] in ("", None)]
    if faltan:
        return {"ok": False, "error": f"faltan datos: {', '.join(faltan)}"}
    nro = _vacio(datos.get("nro_afiliado"))
    try:
        for campo in ALTA:
            validar_texto(datos[campo], campo)
        validar_cobertura(datos["obra_social"], nro)
    except Rechazo as rechazo:
        return {"ok": False, "error": rechazo.mensaje}
    if base().clientes.find_one({"dni": datos["dni"]}):
        return {"ok": False, "error": "ya existe un cliente con ese DNI"}

    documento = {campo: datos[campo] for campo in ALTA}
    documento["nro_afiliado"] = nro
    documento["activo"] = True
    try:
        _insertar(documento)
    except Rechazo as rechazo:
        return {"ok": False, "error": rechazo.mensaje}
    except RuntimeError:
        return {"ok": False, "error": "no se pudo asignar un id de cliente"}
    return _proyectar(documento)


def modificar(id_cliente: str, **datos) -> dict:
    ajenos = [campo for campo in datos if campo not in CONTACTO]
    if ajenos:
        return {"ok": False, "error": "modificar solo admite contacto y cobertura"}
    if not datos:
        return {"ok": False, "error": "no hay datos para modificar"}
    try:
        validar_texto(id_cliente, "id_cliente")
        for campo, valor in datos.items():
            if campo != "nro_afiliado":
                validar_texto(valor, campo)
    except Rechazo as rechazo:
        return {"ok": False, "error": rechazo.mensaje}
    clientes = base().clientes
    actual = clientes.find_one({"_id": id_cliente})
    if actual is None:
        return {"ok": False, "error": "el cliente no existe"}

    obra = datos.get("obra_social", actual["obra_social"])
    if "nro_afiliado" in datos:
        nro = _vacio(datos["nro_afiliado"])
    else:
        nro = actual.get("nro_afiliado")
    try:
        validar_cobertura(obra, nro)
    except Rechazo as rechazo:
        return {"ok": False, "error": rechazo.mensaje}

    cambios = dict(datos)
    if "nro_afiliado" in cambios:
        cambios["nro_afiliado"] = nro
    clientes.update_one({"_id": id_cliente}, {"$set": cambios})
    return _proyectar(clientes.find_one({"_id": id_cliente}))


def baja(id_cliente: str) -> dict:
    try:
        validar_texto(id_cliente, "id_cliente")
    except Rechazo as rechazo:
        return {"ok": False, "error": rechazo.mensaje}
    clientes = base().clientes
    resultado = clientes.update_one({"_id": id_cliente}, {"$set": {"activo": False}})
    if resultado.matched_count != 1:
        return {"ok": False, "error": "el cliente no existe"}
    return _proyectar(clientes.find_one({"_id": id_cliente}))


def _vacio(valor):
    if valor is None or valor == "":
        return None
    return valor


def _insertar(documento: dict) -> None:
    clientes = base().clientes
    for _ in range(5):
        nuevo = _siguiente_id(clientes)
        documento["_id"] = nuevo
        documento["id_cliente"] = nuevo
        try:
            clientes.insert_one(dict(documento))
            return
        except DuplicateKeyError as error:
            if "dni" in str(error):
                raise Rechazo("ya existe un cliente con ese DNI") from error
            continue
    raise RuntimeError("id de cliente")


def _siguiente_id(clientes) -> str:
    maximo = 0
    for doc in clientes.find({}, {"_id": 1}):
        valor = doc["_id"]
        if isinstance(valor, str) and valor.startswith("C"):
            try:
                maximo = max(maximo, int(valor[1:]))
            except ValueError:
                continue
    return f"C{maximo + 1:03d}"


def _proyectar(documento: dict) -> dict:
    respuesta = {"ok": True, "documento": documento}
    if proyectar(upsert_cliente, documento):
        respuesta["aviso_grafo"] = "el grafo quedó pendiente"
    return respuesta
