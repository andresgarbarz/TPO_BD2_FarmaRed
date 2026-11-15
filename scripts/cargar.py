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


def _validar(tablas: dict) -> None:
    ids: dict[str, set[str]] = {}
    for nombre, partes in tablas.items():
        campo = ID_CAMPO[nombre]
        for fila in partes["catedra"] + partes["propios"]:
            for atributo, dominio in DOMINIOS.get(nombre, {}).items():
                if fila[atributo] not in dominio:
                    raise CargaInvalida(f"{nombre}: {atributo} fuera de dominio")
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

    for fila in tablas["recetas.csv"]["catedra"] + tablas["recetas.csv"]["propios"]:
        autorizadas, hechas = int(fila["dispensas_autorizadas"]), int(fila["dispensas_realizadas"])
        maximo = 3 if fila["tipo"] == "Tratamiento prolongado" else 1
        if not (1 <= autorizadas <= maximo and 0 <= hechas <= autorizadas):
            raise CargaInvalida("recetas: cantidad de dispensas inválida")

    matriculas = [fila["matricula"] for origen in ("catedra", "propios")
                  for fila in tablas["farmaceuticos.csv"][origen]]
    if "" in matriculas or len(set(matriculas)) != len(matriculas):
        raise CargaInvalida("farmaceuticos: matrícula vacía o repetida")

    sumas: dict[str, int] = {}
    for fila in tablas["detalle_ventas.csv"]["catedra"] + tablas["detalle_ventas.csv"]["propios"]:
        sumas[fila["id_venta"]] = sumas.get(fila["id_venta"], 0) + int(fila["cantidad"]) * int(fila["precio_unit"])
    for fila in tablas["ventas.csv"]["catedra"] + tablas["ventas.csv"]["propios"]:
        if fila["id_venta"] not in sumas:
            raise CargaInvalida(f"ventas {fila['id_venta']}: la venta no tiene ítems")
        total = int(fila["total"])
        suma = sumas[fila["id_venta"]]
        if total != suma:
            raise CargaInvalida(
                f"ventas {fila['id_venta']}: el total {total} no coincide con la suma de los ítems {suma}"
            )


def _escribir(tablas: dict) -> None:
    _validar(tablas)
    documentos = {}
    for nombre, coleccion in ARCHIVOS.items():
        campo = ID_CAMPO[nombre]
        documentos[coleccion] = [dict(_convertir(fila), _id=fila[campo])
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
    db.clientes.create_index("dni", unique=True, name="dni_unico")
    db.farmaceuticos.create_index("matricula", unique=True, name="matricula_unica")
    iniciar(db, secuencias)
    crear_vista()
    db["_estado_grafo"].update_one(
        {"_id": "reconstruccion"}, {"$set": {"carga_lista": True}})


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
            minimo = 1 if campo in {"cantidad", "dispensas_autorizadas"} else 0
            if not minimo <= entero < 2 ** 63:
                raise ValueError(f"{campo} fuera del rango admitido")
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
