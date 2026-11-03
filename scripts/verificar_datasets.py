"""Comprueba que los CSV provistos estén completos. No carga ningún motor."""

import csv
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DATOS = RAIZ / "datasets"

ESPERADOS = {
    "clientes.csv": (
        8,
        ["id_cliente", "nombre", "apellido", "dni", "email", "telefono", "ciudad", "provincia", "obra_social", "nro_afiliado", "activo"],
    ),
    "sucursales.csv": (
        5,
        ["id_sucursal", "nombre", "tipo", "direccion", "ciudad", "provincia", "telefono", "activo"],
    ),
    "farmaceuticos.csv": (
        7,
        ["id_farmaceutico", "nombre", "apellido", "matricula", "cargo", "id_sucursal", "activo"],
    ),
    "proveedores.csv": (
        5,
        ["id_proveedor", "razon_social", "cuit", "tipo", "ciudad", "provincia", "telefono", "activo"],
    ),
    "productos.csv": (
        13,
        ["id_producto", "nombre", "principio_activo", "categoria", "presentacion", "condicion_venta", "precio_unit", "id_proveedor", "activo"],
    ),
    "stock_lotes.csv": (
        18,
        ["id_lote", "id_producto", "id_sucursal", "nro_lote", "unidades", "vencimiento"],
    ),
    "recetas.csv": (
        9,
        ["id_receta", "id_cliente", "medico", "matricula_medico", "fecha_emision", "tipo", "dispensas_autorizadas", "dispensas_realizadas", "proxima_dispensa", "estado"],
    ),
    "ventas.csv": (
        16,
        ["id_venta", "id_cliente", "id_farmaceutico", "id_receta", "fecha", "tipo", "medio_pago", "total", "estado"],
    ),
    "detalle_ventas.csv": (
        22,
        ["id_detalle", "id_venta", "id_producto", "cantidad", "precio_unit"],
    ),
}


def main() -> int:
    errores = 0
    for nombre, (filas, columnas) in ESPERADOS.items():
        ruta = DATOS / nombre
        if not ruta.is_file():
            print(f"Falta {nombre}")
            errores += 1
            continue
        with ruta.open(newline="", encoding="utf-8") as archivo:
            lector = csv.reader(archivo)
            encabezado = next(lector, None)
            cantidad = sum(1 for _ in lector)
        if encabezado != columnas:
            print(f"{nombre}: columnas distintas de las esperadas")
            errores += 1
        elif cantidad != filas:
            print(f"{nombre}: {cantidad} filas, se esperaban {filas}")
            errores += 1
        else:
            print(f"{nombre}: {cantidad} filas")
    if errores:
        print(f"{errores} problema(s).")
        return 1
    print("Datasets provistos en orden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
