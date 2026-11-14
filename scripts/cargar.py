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

from pymongo.errors import ServerSelectionTimeoutError  # noqa: E402

from db import COLECCIONES, base, fecha_de_partes  # noqa: E402
from consultas.q11 import crear_vista  # noqa: E402
from grafo import GrafoPendiente, proyectar_todo  # noqa: E402

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
        _validar(tablas)
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
    except Exception:
        print("Grafo pendiente: la proyección falló y se rehace con reconstruir().")
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


def _validar(tablas: dict) -> None:
    ids: dict[str, set[str]] = {}
    for nombre, partes in tablas.items():
        campo = ID_CAMPO[nombre]
        catedra = {fila[campo] for fila in partes["catedra"]}
        propios = []
        for fila in partes["propios"]:
            identificador = fila[campo]
            if identificador in catedra or identificador in propios:
                raise CargaInvalida(
                    f"datasets/extra/{nombre}: {identificador} repite un id de la cátedra o del propio archivo"
                )
            propios.append(identificador)
        ids[nombre] = catedra | set(propios)

    for nombre, reglas in REFERENCIAS.items():
        for fila in tablas[nombre]["catedra"] + tablas[nombre]["propios"]:
            for campo, destino in reglas:
                valor = fila[campo]
                if campo in OPCIONALES and valor == "":
                    continue
                if valor not in ids[destino]:
                    raise CargaInvalida(
                        f"{nombre} {fila[ID_CAMPO[nombre]]}: {campo} {valor} no existe"
                    )

    dnis = []
    for fila in tablas["clientes.csv"]["catedra"] + tablas["clientes.csv"]["propios"]:
        if fila["dni"] == "":
            raise CargaInvalida(f"clientes {fila['id_cliente']}: falta el DNI")
        if fila["dni"] in dnis:
            raise CargaInvalida(f"clientes: el DNI {fila['dni']} está repetido")
        dnis.append(fila["dni"])

    sumas: dict[str, int] = {}
    for fila in tablas["detalle_ventas.csv"]["catedra"] + tablas["detalle_ventas.csv"]["propios"]:
        sumas[fila["id_venta"]] = sumas.get(fila["id_venta"], 0) + int(fila["cantidad"]) * int(fila["precio_unit"])
    for fila in tablas["ventas.csv"]["catedra"] + tablas["ventas.csv"]["propios"]:
        total = int(fila["total"])
        suma = sumas.get(fila["id_venta"], 0)
        if total != suma:
            raise CargaInvalida(
                f"ventas {fila['id_venta']}: el total {total} no coincide con la suma de los ítems {suma}"
            )


def _escribir(tablas: dict) -> None:
    db = base()
    for coleccion in COLECCIONES:
        db[coleccion].drop()

    for nombre, coleccion in ARCHIVOS.items():
        if coleccion == "detalle_ventas":
            continue
        campo = ID_CAMPO[nombre]
        documentos = []
        for origen in ("catedra", "propios"):
            for fila in tablas[nombre][origen]:
                documento = _convertir(fila)
                documento["_id"] = documento[campo]
                documentos.append(documento)
        if documentos:
            db[coleccion].insert_many(documentos)
        print(
            f"{coleccion}: {len(tablas[nombre]['catedra'])} de la cátedra, "
            f"{len(tablas[nombre]['propios'])} propios"
        )

    sucursal_de = {
        documento["_id"]: documento["id_sucursal"]
        for documento in db.farmaceuticos.find({}, {"id_sucursal": 1})
    }
    for venta in list(
        db.ventas.find({}, {"id_farmaceutico": 1, "id_sucursal": 1})
    ):
        if not venta.get("id_sucursal"):
            id_sucursal = sucursal_de.get(venta["id_farmaceutico"])
            if id_sucursal:
                db.ventas.update_one(
                    {"_id": venta["_id"]}, {"$set": {"id_sucursal": id_sucursal}}
                )

    detalles: dict[str, list[dict]] = {}
    for origen in ("catedra", "propios"):
        for fila in tablas["detalle_ventas.csv"][origen]:
            item = _convertir(fila)
            item.pop("id_venta")
            detalles.setdefault(fila["id_venta"], []).append(item)
    db.ventas.update_many({}, {"$set": {"items": []}})
    for id_venta, items in detalles.items():
        db.ventas.update_one({"_id": id_venta}, {"$set": {"items": items}})
    print(
        "detalle_ventas: "
        f"{len(tablas['detalle_ventas.csv']['catedra'])} de la cátedra, "
        f"{len(tablas['detalle_ventas.csv']['propios'])} propios, embebidos en ventas"
    )
    db.clientes.create_index("dni", unique=True, name="dni_unico")
    crear_vista()


def _convertir(fila: dict) -> dict:
    documento = {}
    for campo, valor in fila.items():
        if campo in OPCIONALES and valor == "":
            documento[campo] = None
        elif campo == "activo":
            documento[campo] = valor == "True"
        elif campo in ENTEROS:
            documento[campo] = int(valor)
        elif campo in FECHAS:
            documento[campo] = None if valor == "" else fecha_de_partes(valor)
        else:
            documento[campo] = valor
    return documento


if __name__ == "__main__":
    sys.exit(main())
