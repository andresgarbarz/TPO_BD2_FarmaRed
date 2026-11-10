# TPO FarmaRed — Bases de Datos II

Trabajo práctico obligatorio, 2.º cuatrimestre 2026. Red de farmacias con droguería propia. La entrega de la cátedra es este repositorio más un informe PDF. La fecha la define la cátedra.

## Integrantes

- [andresgarbarz](https://github.com/andresgarbarz)
- [SantiagoLifischtz](https://github.com/SantiagoLifischtz)
- [GeronimoAsin](https://github.com/GeronimoAsin)
- [Ftrivelloni](https://github.com/Ftrivelloni)

## Motores

MongoDB guarda los datos y las escrituras. Neo4j guarda el camino entre entidades. `src/grafo.py` expone `reconstruir()`, `upsert_cliente`, `upsert_venta` y `upsert_receta`, vacías hasta que se implemente esa parte. Reciben el documento tal como quedó en Mongo. La carga llama a `reconstruir()` al final; la 13, a `upsert_cliente`; la 14 y la 15, a `upsert_venta` y, si hubo receta, a `upsert_receta`. Si la proyección falla, la escritura en Mongo queda hecha y la consulta avisa que el grafo quedó pendiente. `reconstruir()` lo rehace desde Mongo.

## Entorno

El devcontainer usa Python 3.12 y Docker. Al crearse instala las dependencias y levanta los dos motores. Las URIs están en `MONGO_URI` y `NEO4J_URI`. En el Codespace apuntan a `127.0.0.1`. Fuera de él, si no están definidas, el código usa el mismo localhost.

En Codespaces el arranque es automático. En una máquina propia, con el puerto 27017 libre:

```bash
docker compose up -d
python3 -m pip install -r requirements.txt
python3 scripts/verificar_datasets.py
python3 scripts/cargar.py
```

Si el Python del sistema rechaza `pip`, el mismo comando va dentro de un entorno virtual (`python3 -m venv .venv`). Si otro Mongo ya usa el puerto 27017, hay que liberarlo: el contenedor de esta compose no arranca mientras el puerto esté ocupado.

Mongo es `8.3.11`. El compose fija `GLIBC_TUNABLES=glibc.pthread.rseq=1` porque esa imagen trae `rseq=0` y, en kernels 6.19 a 7.0.13, el proceso se corta al iniciar si glibc también usa rseq. Pasa en Docker Desktop para Mac. Con `rseq=1`, glibc se queda el registro, TCMalloc no lo usa y Mongo arranca. El log muestra un aviso de rendimiento: es el efecto esperado de esa variable. En Codespaces, con kernel 6.8, arranca igual sin ella; queda fija para que el mismo archivo sirva en todas las máquinas.

Neo4j es `5.26.32`, el último parche de la serie 5.26 publicado en Docker Hub, sin autenticación. Los puertos de los dos motores se publican solo en `127.0.0.1`.

## Carga

`python3 scripts/cargar.py` borra las ocho colecciones y las vuelve a llenar desde los CSV. Se puede correr dos veces: la segunda deja el mismo contenido que la primera.

Recargar borra lo creado con las consultas 13 y 14. Una venta que la consulta 15 pasó de Pendiente a Completada vuelve a Pendiente, con la fecha y los ítems del archivo.

Los ejemplos de las consultas 1 a 12 se sacan con una carga recién hecha, porque la 13, la 14 y la 15 cambian lo que esas consultas leen.

La carga también crea o actualiza la vista `ingresos_mensuales_farmaceutico` de Q11. No guarda un mes fijo: agrupa por farmacéutico, año y mes; Q11 consulta el período actual.

### Colecciones

`_id` es el id de la cátedra (`C001`, `V001`). Los demás campos conservan el nombre del CSV. Los booleanos son booleanos, los importes son enteros y las fechas son `Date` armados con año, mes y día. El proveedor del producto queda referenciado con `id_proveedor`. Hay un índice único sobre `clientes.dni`.

| Colección | Origen |
|---|---|
| `clientes` | `clientes.csv` |
| `sucursales` | `sucursales.csv` |
| `farmaceuticos` | `farmaceuticos.csv` |
| `proveedores` | `proveedores.csv` |
| `productos` | `productos.csv` |
| `stock_lotes` | `stock_lotes.csv` |
| `recetas` | `recetas.csv` |
| `ventas` | `ventas.csv` más sus ítems |

No hay colección de detalle. Cada venta tiene un arreglo `items` con `id_detalle`, `id_producto`, `cantidad` y `precio_unit`.

Dos campos no vienen en los CSV:

- `items.lotes`: lo escriben las consultas 14 y 15. Es una lista de `{id_lote, unidades}` con los lotes de los que salió ese ítem.
- `fecha_registro`: lo escribe solo la consulta 15. En una venta Completada, `fecha` es el día en que computa ingresos. Si la completó la 15, `fecha` es el día de la entrega y la reserva queda en `fecha_registro`. Las consultas 3, 5, 11 y 12 usan `fecha`. La 11 suma el mes de esa fecha, así que una reserva de octubre completada en noviembre entra en noviembre.

### Registros extra

Van en `datasets/extra/`, con el mismo nombre y los mismos encabezados que el archivo de la cátedra. Los id siguen la serie (`C009`, `V017`, `L019`). Si el archivo no está, esa colección se carga solo con los datos de la cátedra y la carga avisa que no hay registros propios.

La carga informa, por colección, cuántos documentos son de la cátedra y cuántos propios. Falla si un id propio repite uno de la cátedra, si una referencia no existe o si el total de una venta no coincide con sus ítems.

Para un caso FEFO que no dependa de la fecha, hace falta un producto con dos lotes de vencimiento lejano en una misma farmacia, y dos lotes que venzan el mismo día.

## Consultas

Desde `src/`:

```bash
python3 -m consultas
```

Eso lista las quince consultas. Las que reciben parámetros son q03, q10, q13, q14 y q15. q14 y q15 descuentan stock antes de confirmar la venta: si no alcanza, no quedan ni la venta ni la receta modificadas.

Están implementadas Q01, Q05, Q07, Q08, Q09, Q11 y Q13–Q15. Quedan pendientes Q02, Q03, Q04, Q06, Q10 y Q12, además del grafo.

Las seis lecturas devuelven una lista de documentos, sin argumentos. Después de cargar los datos, desde `src/`:

```bash
python3 -c "from consultas.q01 import ejecutar; print(ejecutar())"
python3 -c "from consultas.q05 import ejecutar; print(ejecutar())"
python3 -c "from consultas.q07 import ejecutar; print(ejecutar())"
python3 -c "from consultas.q08 import ejecutar; print(ejecutar())"
python3 -c "from consultas.q09 import ejecutar; print(ejecutar())"
python3 -c "from consultas.q11 import ejecutar; print(ejecutar())"
```

Q05 cuenta 60 días incluyendo hoy: desde `hoy() - 59 días` inclusive hasta mañana exclusivo, con la fecha de Argentina. Q11 usa el año y mes de `hoy()`. Con los CSV provistos, sin extras, noviembre de 2026 no tiene ingresos: Q11 devuelve `[]`. Los ejemplos, retornos y decisiones están en [docs/informe-consultas-lectura.md](docs/informe-consultas-lectura.md).

### Pruebas de las consultas

Con MongoDB levantado y las dependencias instaladas, desde la raíz del proyecto:

```bash
python3 -m unittest discover -s tests -v
```

Las 17 pruebas requieren MongoDB real; fallan si no está disponible. Cargan los nueve CSV provistos en una base temporal `farmared_test_<id>`, agregan casos borde y eliminan esa base al terminar. No borran ni recargan la base `farmared`. Usan la URI de `MONGO_URI` (por defecto `mongodb://127.0.0.1:27017`). Para otra instancia, por ejemplo:

```bash
MONGO_URI=mongodb://127.0.0.1:27018 python3 -m unittest discover -s tests -v
```

La 13, la 14 y la 15 se ejecutan así, con el directorio actual en `src/`:

```bash
python3 -c "from consultas.q13 import ejecutar; print(ejecutar('baja', id_cliente='C009'))"
python3 -c "from consultas.q14 import ejecutar; print(ejecutar('C006', 'F001', [{'id_producto': 'PRD003', 'cantidad': 50}], 'Obra social', 'RC003'))"
python3 -c "from consultas.q15 import ejecutar; print(ejecutar('V011'))"
```

La 14 no recibe la fecha: usa el día de hoy en Argentina. La 15 recibe el id de una venta Pendiente. El alta de la 13 y la venta de la 14 generan el siguiente id (`C009`, `V017`, `D023`).

El antes y el después de los casos de esta parte, y las decisiones de consistencia, están en [docs/informe-entorno-y-escrituras.md](docs/informe-entorno-y-escrituras.md).

## Datasets

Están en `datasets/`, en UTF-8 y separados por coma. La referencia temporal de la consigna es el 2026-10-13. Los campos vacíos son nulos, los booleanos son `True`/`False`, las fechas son ISO y los importes son enteros en pesos.

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

Hay que sumar al menos 10 registros propios por colección, con casos borde. La carga los toma de `datasets/extra/`.

## Estructura

```text
.devcontainer/     Codespaces
compose.yaml       MongoDB y Neo4j
datasets/          CSV provistos
datasets/extra/    registros propios, si existen
docs/              material de esta parte para el informe
scripts/           verificación y carga
src/db.py          conexión y hoy()
src/grafo.py       proyección vacía
src/consultas/     q01.py … q15.py
tests/             integración de las seis lecturas contra MongoDB real
```
