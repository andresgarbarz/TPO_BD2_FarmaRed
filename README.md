# TPO FarmaRed — Bases de Datos II

Trabajo práctico obligatorio, 2.º cuatrimestre 2026. Red de farmacias con droguería propia. La entrega de la cátedra es este repositorio más un informe PDF. La fecha la define la cátedra.

## Integrantes

- [andresgarbarz](https://github.com/andresgarbarz)
- [SantiagoLifischtz](https://github.com/SantiagoLifischtz)
- [GeronimoAsin](https://github.com/GeronimoAsin)
- [Ftrivelloni](https://github.com/Ftrivelloni)

## Estado de esta base

El repositorio abre en GitHub Codespaces, trae los nueve CSV de la consigna y deja un módulo vacío por consulta (`q01` a `q15`).

Todavía no hay motores, modelo ni implementación. Elegir al menos dos motores NoSQL de paradigmas distintos, justificarlos en el informe y escribir las consultas es el trabajo del grupo. `docker-compose` se agrega cuando esos motores estén decididos.

## Codespaces

Abrí el repositorio en un Codespace. El devcontainer usa Python 3.12 y, al crearse, corre la verificación de los CSV.

En una terminal del Codespace, o en una copia local:

```bash
python3 scripts/verificar_datasets.py
python3 -m consultas
```

El segundo comando se corre desde `src/`. Lista las quince consultas y no las ejecuta.

## Datasets

Están en `datasets/`, en UTF-8 y separados por coma. Son los archivos provistos, sin registros extra. La referencia temporal de la consigna es el 2026-10-13. Los campos vacíos son nulos, los booleanos son `True`/`False`, las fechas son ISO y los importes son enteros en pesos.

| Archivo | Filas |
|---|---|
| `clientes.csv` | 8 |
| `sucursales.csv` | 5 |
| `farmaceuticos.csv` | 7 |
| `proveedores.csv` | 5 |
| `productos.csv` | 13 |
| `stock_lotes.csv` | 18 |
| `recetas.csv` | 9 |
| `ventas.csv` | 16 |
| `detalle_ventas.csv` | 22 |

Hay que sumar al menos 10 registros propios por colección o tabla, con casos borde, y una carga reproducible e idempotente.

## Consultas

Cada módulo documenta el pedido, los parámetros y el motor. `ejecutar` lanza `NotImplementedError`. Las que reciben parámetros son q03, q10, q13, q14 y q15. q14 y q15 tienen que quedar integradas: si el descuento de stock falla, no deben quedar ni la venta ni la receta modificadas.

## Estructura

```text
.devcontainer/     Codespaces
datasets/          CSV provistos
scripts/           verificación de esos CSV
src/consultas/     q01.py … q15.py
```
