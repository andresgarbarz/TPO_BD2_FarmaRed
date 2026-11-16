# Entorno, carga y escrituras

Material de la parte de entorno, carga y consultas 13, 14 y 15 para el informe. La fecha de ejecución de los ejemplos es el 2026-11-15. Ese día `hoy()` devolvió el 2026-11-15, así que el lote `L005`, que vence el 2026-11-30, todavía se podía vender. Desde el 2026-12-01 ese lote queda vencido y las 50 unidades de amoxicilina salen todas de `L015`.

Los ejemplos se tomaron sobre una carga recién hecha, con los CSV de la cátedra y `datasets/extra/`. Recargar borra el cliente y las ventas creados con las consultas 13 y 14, y devuelve a Pendiente la venta que completó la 15.

## Estrategia de carga

`scripts/cargar.py` borra las ocho colecciones y las vuelve a insertar desde los CSV. El 2026-11-15 dejó 18 clientes, 26 ventas y 33 ítems embebidos: 8, 16 y 22 de la cátedra, más 10, 10 y 11 propios.

Cada archivo de `datasets/extra/` se carga si existe, con el mismo nombre y los mismos encabezados. La salida informa, por colección, cuántos documentos son de la cátedra y cuántos propios. Sin esa carpeta, avisa que no hay registros propios. Un id propio que repite uno de la cátedra frena la carga. Una referencia inexistente también: no se escribe nada.

Las fechas se guardan como `Date` armados con año, mes y día. `_id` es el id de la cátedra. Hay un índice único `dni_unico` sobre `clientes.dni`. Al final se llama a `proyectar_todo()`. Si Neo4j no está disponible, la carga avisa que el grafo quedó pendiente.

## Consulta 13

ABM de clientes en MongoDB. `ejecutar(operacion, **datos)` llama a `alta`, `modificar(id_cliente, ...)` o `baja(id_cliente)`. El alta genera el id siguiente (`C019`). Modificar solo admite email, teléfono, ciudad, provincia, obra social y número de afiliado. Tratar ciudad y provincia como contacto es un supuesto: la consigna las llama domicilio. La baja pone `activo` en false y no borra el documento. Después se llama a `upsert_cliente`.

Antes: 18 clientes. `C008` (Hugo Mansilla) tiene DNI `25678901` y `activo` en false. `C009` ya existe: es Lionel Messi, un registro propio.

| Caso | Resultado | Después |
|---|---|---|
| Alta con el DNI `25678901` | Rechazo: ya existe un cliente con ese DNI | Siguen 18 clientes |
| Alta en OSDE sin número de afiliado | Rechazo: la obra social exige número de afiliado | Siguen 18 clientes |
| Alta de Ana Prueba, DNI `30111222`, OSDE, afiliado `99` | `C019`, `activo` true | 19 clientes |
| Modificar el email de `C019` a `ana2@x.com` | El documento queda con ese email | El resto no cambia |
| Baja de `C019` | `activo` pasa a false | El documento sigue; siguen 19 clientes |

La cobertura válida es OSDE, Swiss Medical, PAMI, IOMA, Galeno o Sin cobertura. El número de afiliado va vacío solo con Sin cobertura.

## Consulta 14

Registro de una venta nueva Completada en MongoDB. El llamador manda `id_producto` y `cantidad`. El servicio copia `precio_unit` del producto y el total es la suma. No recibe la fecha: usa `hoy()`.

Antes, con la carga recién hecha: 26 ventas; `L005` en `S001` con 40 unidades y vencimiento 2026-11-30; `L015` en `S001` con 100 unidades y vencimiento 2027-06-30; `RC003` vigente, 2 de 3, próxima 2026-10-01; `RC004` vigente, 1 de 3, próxima 2026-10-20. El precio de `PRD003` es 9800. Las filas exitosas se ejecutaron en ese orden, sobre el estado que dejó la anterior.

| Caso | Resultado | Lotes y receta |
|---|---|---|
| 200 unidades de `PRD003` en `S001`, con `F001` y `RC004` | Rechazo: no hay stock vigente de `PRD003` en `S001` | Sin cambios. Siguen 26 ventas |
| 1 unidad de `PRD003` con `F007` | Rechazo: el farmacéutico no pertenece a una sucursal de tipo Farmacia | Sin cambios. `F007` es de la droguería |
| 50 unidades de `PRD003`, `F001`, `C006`, `RC003`, obra social | `V027`, total 490000, Completada, fecha 2026-11-15, ítem `D034` | 40 de `L005` y 10 de `L015`. `L005` queda en 0 y `L015` en 90. `RC003` pasa a Completada, 3 de 3, sin próxima dispensa |
| 50 unidades de `PRD003`, `F001`, `C006`, `RC004`, obra social | `V028`, ítem `D035`, las 50 de `L015` | `L015` queda en 40. `RC004` sigue Vigente, 2 de 3, y la próxima dispensa pasa al 2026-12-15, treinta días después del 2026-11-15 |

## Consulta 15

Completa una venta que ya está Pendiente. Descuenta por FEFO en la sucursal del farmacéutico, actualiza la receta y, solo si todo alcanzó, la pasa a Completada. `fecha` pasa a ser el día de la entrega, que es cuando computa ingresos. La reserva queda en `fecha_registro`. Los precios no se recalculan.

Antes: `V011` Pendiente, fecha 2026-10-12, una unidad de `PRD007` a 4800, receta `RC006`. `L014` en `S004` tiene 45 unidades. `RC006` es simple, vigente, 0 de 1. `V012` está Pendiente y `S003` no tiene lotes de sus productos. `V003` ya está Completada.

| Caso | Resultado | Después |
|---|---|---|
| `V003` | Rechazo: la venta está Completada; solo se completa una Pendiente | Ningún lote cambia |
| `V012` | Rechazo: no hay stock vigente de `PRD002` en `S003` | Sigue Pendiente, con su fecha y sus ítems. Ningún lote cambia |
| `V011` | Completada, fecha 2026-11-15, `fecha_registro` 2026-10-12, el ítem `D014` sale de `L014` | `L014` pasa de 45 a 44. `RC006` queda Completada, 1 de 1, sin próxima dispensa |

En una venta Completada, `fecha` es el día que usan las consultas 3, 5, 11 y 12. Una reserva de octubre completada en noviembre entra en noviembre. `fecha_registro` solo conserva el día de la reserva.

## Consistencia de la 14 y la 15

Las dos tienen que quedar integradas: si el descuento falla, no pueden quedar una venta ni una receta modificadas. Comparten `descontar(id_sucursal, items)`.

El plan FEFO lee los lotes con `vencimiento` mayor o igual a `hoy()`, ordenados por `{vencimiento: 1, _id: 1}`. El día de vencimiento todavía se vende. El `sort` de MongoDB no es estable, y `_id` es el id del lote, así que dos lotes que vencen el mismo día salen siempre en el mismo orden. Si dos ítems piden el mismo producto, el plan descuenta en memoria lo ya asignado para no usar dos veces las mismas unidades.

La implementación posterior a la auditoría confirma lotes, receta, contadores y venta en una transacción MongoDB. El entorno inicia automáticamente un replica set `rs0` de un nodo. Un rechazo o error de escritura aborta todos los cambios; los conflictos transitorios reintentan la transacción. La proyección Neo4j se realiza después del commit. Ya no se restauran snapshots de recetas ni se reponen lotes por compensación.

Q15 lee y completa la venta dentro de la transacción, de modo que dos llamadas simultáneas no consumen dos dispensas. Descuenta en la sucursal actual del farmacéutico y la guarda en la venta completada. Q14 rechaza una receta en ventas exclusivamente libres y valida cantidades enteras positivas antes de escribir. Estas decisiones del proyecto mantienen las reglas de venta, stock e integración.

Los correlativos C/V/D usan contadores atómicos, inicializados por la carga. No se migran bases anteriores automáticamente. Q13 modifica la cobertura sólo si sigue siendo la que validó. DNI y matrícula se protegen con índices únicos.

Las escrituras de clientes, recetas y ventas incrementan `_version` y marcan `grafo_pendiente` en la misma operación. Neo4j descarta proyecciones anteriores a su versión actual; la confirmación limpia sólo la versión correspondiente. Q02/Q03/Q10 fallan explícitamente si el grafo está pendiente; se debe ejecutar `reconstruir()` para actualizarlo. Una reconstrucción completa tiene un marcador persistente; una carga incompleta exige repetir el cargador. Ver [informe-grafo.md](informe-grafo.md).

La carga valida y convierte todos los CSV y prepara los documentos completos antes del primer borrado. Sigue siendo una operación de reinicio que debe correr sin escrituras concurrentes. Los ejemplos de esta página se volvieron a ejecutar el 2026-11-15 y después se recargaron los CSV.

## Limitación y supuestos

`compose.yaml` fija `GLIBC_TUNABLES=glibc.pthread.rseq=1` en Mongo `8.3.11`. La imagen trae `rseq=0` y, en kernels 6.19 a 7.0.13, el proceso se corta al iniciar si glibc también usa rseq. Pasa en Docker Desktop para Mac. Con `rseq=1` glibc se queda el registro, TCMalloc no lo usa y Mongo arranca. El log muestra un aviso de rendimiento: es el efecto esperado y con estos datos no importa. En Codespaces, con kernel 6.8, arranca igual sin la variable. Queda fija para que el mismo archivo sirva en todas las máquinas. El 2026-11-07 el tag `neo4j:5.26.33` no estaba en Docker Hub; el compose usa `neo4j:5.26.32`, el último parche publicado de esa serie.

Supuestos de esta parte: ciudad y provincia se modifican como datos de contacto, y la consulta 15 es el paso de una venta Pendiente a Completada. Ese paso mueve `fecha` al día de la entrega y guarda la reserva en `fecha_registro`.
