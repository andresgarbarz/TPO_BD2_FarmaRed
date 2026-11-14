"""Carga idempotente de los CSV en MongoDB.

Borra las ocho colecciones y las vuelve a llenar. Una segunda corrida deja el
mismo contenido que la primera. Lo creado solo con las consultas 13 y 14 se
pierde, y una venta que la 15 pasó a Completada vuelve a Pendiente.

Lee datasets/ y, si existe, datasets/extra/ con los mismos nombres y encabezados.
Los id propios no pueden repetir uno de la cátedra. Las referencias tienen que
existir y el total de cada venta tiene que coincidir con sus ítems. A cada venta
se le agrega el id_sucursal del farmacéutico para conservar la sucursal histórica.
"""

import csv
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from bson import BSON  # noqa: E402
from pymongo.errors import ServerSelectionTimeoutError  # noqa: E402

from db import COLECCIONES, base, fecha_de_partes  # noqa: E402
from consultas.q11 import crear_vista  # noqa: E402
from grafo import COLECCIONES_PENDIENTES, GrafoPendiente, proyectar_todo  # noqa: E402
from ids import desde_documentos, iniciar  # noqa: E402

DATOS = RAIZ / "datasets"
EXTRA = DATOS / "extra"

ARCHIVOS = {
    "clientes.csv": "clientes",
    "sucursales.csv": "sucursales",
    "farmaceuticos.csv": "farmaceuticos",
    "proveedores.csv": "proveedores",
    "productos.csv": "productos",
    "stock_lotes.csv": "stock_lotes",
    "recetas.csv": "recetas",
    "ventas.csv": "ventas",
    "detalle_ventas.csv": "detalle_ventas",
}

COLUMNAS = {
    "clientes.csv": ["id_cliente", "nombre", "apellido", "dni", "email", "telefono", "ciudad", "provincia", "obra_social", "nro_afiliado", "activo"],
    "sucursales.csv": ["id_sucursal", "nombre", "tipo", "direccion", "ciudad", "provincia", "telefono", "activo"],
    "farmaceuticos.csv": ["id_farmaceutico", "nombre", "apellido", "matricula", "cargo", "id_sucursal", "activo"],
    "proveedores.csv": ["id_proveedor", "razon_social", "cuit", "tipo", "ciudad", "provincia", "telefono", "activo"],
    "productos.csv": ["id_producto", "nombre", "principio_activo", "categoria", "presentacion", "condicion_venta", "precio_unit", "id_proveedor", "activo"],
    "stock_lotes.csv": ["id_lote", "id_producto", "id_sucursal", "nro_lote", "unidades", "vencimiento"],
    "recetas.csv": ["id_receta", "id_cliente", "medico", "matricula_medico", "fecha_emision", "tipo", "dispensas_autorizadas", "dispensas_realizadas", "proxima_dispensa", "estado"],
    "ventas.csv": ["id_venta", "id_cliente", "id_farmaceutico", "id_receta", "fecha", "tipo", "medio_pago", "total", "estado"],
    "detalle_ventas.csv": ["id_detalle", "id_venta", "id_producto", "cantidad", "precio_unit"],
}

ID_CAMPO = {nombre: columnas[0] for nombre, columnas in COLUMNAS.items()}

ENTEROS = {
    "precio_unit",
    "unidades",
    "cantidad",
    "dispensas_autorizadas",
    "dispensas_realizadas",
    "total",
}
FECHAS = {"vencimiento", "fecha_emision", "proxima_dispensa", "fecha"}
OPCIONALES = {"nro_afiliado", "proxima_dispensa", "id_receta"}

REFERENCIAS = {
    "farmaceuticos.csv": [("id_sucursal", "sucursales.csv")],
    "productos.csv": [("id_proveedor", "proveedores.csv")],
    "stock_lotes.csv": [("id_producto", "productos.csv"), ("id_sucursal", "sucursales.csv")],
    "recetas.csv": [("id_cliente", "clientes.csv")],
    "ventas.csv": [
        ("id_cliente", "clientes.csv"),
        ("id_farmaceutico", "farmaceuticos.csv"),
        ("id_receta", "recetas.csv"),
    ],
    "detalle_ventas.csv": [("id_venta", "ventas.csv"), ("id_producto", "productos.csv")],
}


class CargaInvalida(Exception):
    pass


def main() -> int:
    try:
        tablas = _leer_todo()
        _escribir(tablas)
    except CargaInvalida as error:
        print(error)
        return 1
    except ServerSelectionTimeoutError:
        print("No hay MongoDB en MONGO_URI. Levantá el entorno con docker compose up -d.")
        return 1

    try:
        proyectar_todo()
    except GrafoPendiente:
        print("Grafo pendiente: no se pudo proyectar. Se rehace con reconstruir().")
        return 1
    except Exception:
        print("Grafo pendiente: la proyección falló y se rehace con reconstruir().")
        return 1
    print("Carga lista.")
    return 0


def _leer_todo() -> dict[str, dict[str, list[dict]]]:
    tablas = {}
    for nombre in ARCHIVOS:
        oficial = _leer(DATOS / nombre, nombre, exigir=True)
        extra_ruta = EXTRA / nombre
        if extra_ruta.is_file():
            propio = _leer(extra_ruta, nombre, exigir=True)
        else:
            propio = []
            print(f"aviso: no hay registros propios en {nombre}")
        tablas[nombre] = {"catedra": oficial, "propios": propio}
    return tablas


def _leer(ruta: Path, nombre: str, exigir: bool) -> list[dict]:
    if not ruta.is_file():
        if exigir:
            raise CargaInvalida(f"falta {ruta.relative_to(RAIZ)}")
        return []
    with ruta.open(newline="", encoding="utf-8") as archivo:
        lector = csv.DictReader(archivo)
        if lector.fieldnames != COLUMNAS[nombre]:
            raise CargaInvalida(f"{ruta.relative_to(RAIZ)}: columnas distintas de las de la cátedra")
        return list(lector)


DOMINIOS = {
    "clientes.csv": {"obra_social": {"OSDE", "Swiss Medical", "PAMI", "IOMA", "Galeno", "Sin cobertura"}},
    "sucursales.csv": {"tipo": {"Farmacia", "Droguería"}},
    "farmaceuticos.csv": {"cargo": {"Director Técnico", "Farmacéutico"}},
    "proveedores.csv": {"tipo": {"Laboratorio", "Droguería"}},
    "productos.csv": {"condicion_venta": {"Venta libre", "Bajo receta", "Bajo receta archivada"}},
    "recetas.csv": {"tipo": {"Simple", "Archivada", "Tratamiento prolongado"},
                    "estado": {"Vigente", "Completada", "Vencida"}},
    "ventas.csv": {"tipo": {"Venta libre", "Con receta"},
                   "estado": {"Completada", "Pendiente", "Anulada"},
                   "medio_pago": {"Efectivo", "Débito", "Crédito", "Transferencia", "Obra social"}},
}


def _validar(tablas: dict) -> dict:
    """Convierte y valida todas las filas sin escribir ni modificar la entrada."""
    convertidas = {}
    ids = {}
    for nombre, partes in tablas.items():
        convertidas[nombre] = {}
        ids[nombre] = set()
        for origen in ("catedra", "propios"):
            convertidas[nombre][origen] = []
            for numero, fila in enumerate(partes[origen], 1):
                contexto = f"{nombre} ({origen}, fila {numero})"
                if (not isinstance(fila, dict) or set(fila) != set(COLUMNAS[nombre])
                        or any(not isinstance(valor, str) for valor in fila.values())):
                    raise CargaInvalida(f"{contexto}: columnas o valores inválidos")
                try:
                    documento = _convertir(fila)
                except (ValueError, TypeError, OverflowError) as error:
                    raise CargaInvalida(f"{contexto}: {error}") from error
                identificador = documento[ID_CAMPO[nombre]]
                if not identificador or identificador in ids[nombre]:
                    raise CargaInvalida(f"{contexto}: el id está vacío o repetido")
                ids[nombre].add(identificador)
                for campo, dominio in DOMINIOS.get(nombre, {}).items():
                    if documento[campo] not in dominio:
                        raise CargaInvalida(f"{contexto}: {campo} fuera de dominio")
                for campo in ENTEROS.intersection(documento):
                    minimo = 1 if campo in {"cantidad", "dispensas_autorizadas"} else 0
                    if documento[campo] < minimo:
                        raise CargaInvalida(f"{contexto}: {campo} debe ser al menos {minimo}")
                convertidas[nombre][origen].append(documento)

    filas = {nombre: partes["catedra"] + partes["propios"]
             for nombre, partes in convertidas.items()}
    for nombre, reglas in REFERENCIAS.items():
        for fila in filas[nombre]:
            for campo, destino in reglas:
                valor = fila[campo]
                if campo in OPCIONALES and valor is None:
                    continue
                if valor not in ids[destino]:
                    raise CargaInvalida(f"{nombre} {fila[ID_CAMPO[nombre]]}: {campo} {valor} no existe")

    dnis = set()
    for fila in filas["clientes.csv"]:
        if not fila["dni"] or fila["dni"] in dnis:
            raise CargaInvalida("clientes: DNI vacío o repetido")
        dnis.add(fila["dni"])
        if (fila["obra_social"] == "Sin cobertura") != (fila["nro_afiliado"] is None):
            raise CargaInvalida(f"clientes {fila['id_cliente']}: cobertura y afiliado incompatibles")

    matriculas = set()
    for fila in filas["farmaceuticos.csv"]:
        if not fila["matricula"] or fila["matricula"] in matriculas:
            raise CargaInvalida("farmaceuticos: matrícula vacía o repetida")
        matriculas.add(fila["matricula"])

    for fila in filas["recetas.csv"]:
        autorizadas, hechas = fila["dispensas_autorizadas"], fila["dispensas_realizadas"]
        maximo = 3 if fila["tipo"] == "Tratamiento prolongado" else 1
        if autorizadas > maximo or hechas > autorizadas:
            raise CargaInvalida(f"recetas {fila['id_receta']}: cantidad de dispensas inválida")
        if ((fila["estado"] == "Completada" and hechas != autorizadas)
                or (fila["estado"] == "Vigente" and hechas == autorizadas)):
            raise CargaInvalida(f"recetas {fila['id_receta']}: estado incompatible con las dispensas")
        proxima = fila["proxima_dispensa"]
        if proxima is not None and (fila["tipo"] != "Tratamiento prolongado"
                or fila["estado"] == "Completada"):
            raise CargaInvalida(f"recetas {fila['id_receta']}: próxima dispensa incompatible")

    recetas = {r["id_receta"]: r for r in filas["recetas.csv"]}
    farmaceuticos = {f["id_farmaceutico"]: f for f in filas["farmaceuticos.csv"]}
    sucursales = {s["id_sucursal"]: s for s in filas["sucursales.csv"]}
    sumas = {}
    for fila in filas["detalle_ventas.csv"]:
        sumas[fila["id_venta"]] = sumas.get(fila["id_venta"], 0) + fila["cantidad"] * fila["precio_unit"]
    for fila in filas["ventas.csv"]:
        if fila["id_venta"] not in sumas or fila["total"] != sumas[fila["id_venta"]]:
            raise CargaInvalida(f"ventas {fila['id_venta']}: el total no coincide con sus ítems")
        receta = recetas.get(fila["id_receta"])
        if ((fila["tipo"] == "Venta libre") != (receta is None)
                or (receta is not None and receta["id_cliente"] != fila["id_cliente"])):
            raise CargaInvalida(f"ventas {fila['id_venta']}: tipo, receta o cliente incompatibles")
        sucursal = sucursales[farmaceuticos[fila["id_farmaceutico"]]["id_sucursal"]]
        if sucursal["tipo"] != "Farmacia":
            raise CargaInvalida(f"ventas {fila['id_venta']}: la sucursal no es una Farmacia")
    return convertidas


def _escribir(tablas: dict) -> None:
    tablas = _validar(tablas)
    documentos = {}
    for nombre, coleccion in ARCHIVOS.items():
        campo = ID_CAMPO[nombre]
        documentos[coleccion] = [dict(fila, _id=fila[campo])
                                for origen in ("catedra", "propios")
                                for fila in tablas[nombre][origen]]
    sucursal_de = {f["_id"]: f["id_sucursal"] for f in documentos["farmaceuticos"]}
    detalles = {}
    for detalle in documentos.pop("detalle_ventas"):
        detalle.pop("_id")
        id_venta = detalle.pop("id_venta")
        detalles.setdefault(id_venta, []).append(detalle)
    for venta in documentos["ventas"]:
        venta["id_sucursal"] = sucursal_de[venta["id_farmaceutico"]]
        venta["items"] = detalles[venta["_id"]]
    for coleccion, filas in documentos.items():
        for documento in filas:
            if coleccion in COLECCIONES_PENDIENTES:
                documento.update({"_version": 0, "grafo_pendiente": True})
            if len(BSON.encode(documento)) > 16 * 1024 * 1024:
                raise CargaInvalida(f"{coleccion} {documento['_id']}: supera el tamaño máximo BSON")

    try:
        secuencias = desde_documentos(documentos)
    except ValueError as error:
        raise CargaInvalida(str(error)) from error

    db = base()
    db["_estado_grafo"].replace_one(
        {"_id": "reconstruccion"}, {"carga_lista": False}, upsert=True)
    for coleccion in COLECCIONES:
        db[coleccion].drop()
    for nombre, coleccion in ARCHIVOS.items():
        if coleccion == "detalle_ventas":
            continue
        if documentos[coleccion]:
            db[coleccion].insert_many(documentos[coleccion])
        print(f"{coleccion}: {len(tablas[nombre]['catedra'])} de la cátedra, "
              f"{len(tablas[nombre]['propios'])} propios")
    print("detalle_ventas: "
          f"{len(tablas['detalle_ventas.csv']['catedra'])} de la cátedra, "
          f"{len(tablas['detalle_ventas.csv']['propios'])} propios, embebidos en ventas")
    crear_indices()
    iniciar(db, secuencias)
    crear_vista()
    db["_estado_grafo"].update_one(
        {"_id": "reconstruccion"}, {"$set": {"carga_lista": True}})


def crear_indices() -> None:
    """Crea los índices de la carga sin borrar ni recargar documentos."""
    db = base()
    db.clientes.create_index("dni", unique=True, name="dni_unico")
    db.farmaceuticos.create_index("matricula", unique=True, name="matricula_unica")
    db.ventas.create_index([("id_farmaceutico", 1), ("fecha", 1)], name="ventas_farmaceutico_fecha")
    db.ventas.create_index([("id_cliente", 1), ("fecha", 1)], name="ventas_cliente_fecha")
    db.ventas.create_index([("estado", 1), ("fecha", 1)], name="ventas_estado_fecha")
    db.stock_lotes.create_index(
        [("id_producto", 1), ("id_sucursal", 1), ("vencimiento", 1), ("_id", 1)], name="lotes_fefo")

    for nombre in COLECCIONES_PENDIENTES:
        db[nombre].create_index("grafo_pendiente")



def _convertir(fila: dict) -> dict:
    documento = {}
    for campo, valor in fila.items():
        if valor == "" and campo not in ENTEROS | (FECHAS - {"proxima_dispensa"}) | {"activo"}:
            documento[campo] = None
        elif campo == "activo":
            if valor not in {"True", "False"}:
                raise ValueError("activo debe ser True o False")
            documento[campo] = valor == "True"
        elif campo in ENTEROS:
            entero = int(valor)
            if not -(2 ** 63) <= entero < 2 ** 63:
                raise ValueError(f"{campo} excede el rango de enteros BSON")
            documento[campo] = entero
        elif campo in FECHAS:
            fecha = fecha_de_partes(valor)
            if valor != f"{fecha.year:04d}-{fecha.month:02d}-{fecha.day:02d}":
                raise ValueError(f"{campo} debe usar AAAA-MM-DD")
            documento[campo] = fecha
        else:
            documento[campo] = valor
    return documento


if __name__ == "__main__":
    sys.exit(main())
