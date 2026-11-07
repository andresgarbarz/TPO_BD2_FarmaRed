# Entorno, carga y escrituras

Material de la parte de entorno, carga y consultas 13, 14 y 15 para el informe. La fecha de ejecución de los ejemplos es el 2026-11-07. Ese día `hoy()` devolvió el 2026-11-07, así que el lote `L005`, que vence el 2026-11-30, todavía se podía vender. Desde el 2026-12-01 ese lote queda vencido y las 50 unidades de amoxicilina salen todas de `L015`.

Los ejemplos se tomaron sobre una carga recién hecha. Recargar borra el cliente y las ventas creados con las consultas 13 y 14, y devuelve a Pendiente la venta que completó la 15.

## Estrategia de carga

`scripts/cargar.py` borra las ocho colecciones y las vuelve a insertar desde los CSV. Se corrió dos veces seguidas: las dos dejaron 8 clientes, 16 ventas y 22 ítems embebidos, que son los conteos de `scripts/verificar_datasets.py`.

Cada archivo de `datasets/extra/` se carga si existe, con el mismo nombre y los mismos encabezados. La salida informa, por colección, cuántos documentos son de la cátedra y cuántos propios. Sin esa carpeta, avisa que no hay registros propios. Un extra con el id `C001`, que ya trae la cátedra, frenó la carga. Una venta `V017` con `id_cliente` `C999` también: la referencia no existe y no se escribió nada.

Las fechas se guardan como `Date` armados con año, mes y día. `_id` es el id de la cátedra. Hay un índice único `dni_unico` sobre `clientes.dni`. Al final se llama a `reconstruir()`. Como Neo4j todavía no está implementado, la carga avisa que el grafo quedó pendiente.

## Consulta 13

ABM de clientes en MongoDB [P18, p. 6]. `ejecutar(operacion, **datos)` llama a `alta`, `modificar(id_cliente, ...)` o `baja(id_cliente)`. El alta genera el id (`C009`). Modificar solo admite email, teléfono, ciudad, provincia, obra social y número de afiliado. Tratar ciudad y provincia como contacto es un supuesto: la consigna las llama domicilio. La baja pone `activo` en false y no borra el documento [P18, p. 5]. Después se llama a `upsert_cliente`.

Antes: 8 clientes. `C008` (Hugo Mansilla) tiene DNI `25678901` y `activo` en false.

| Caso | Resultado | Después |
|---|---|---|
| Alta con el DNI `25678901` | Rechazo: ya existe un cliente con ese DNI | Siguen 8 clientes |
| Alta en OSDE sin número de afiliado | Rechazo: la obra social exige número de afiliado | Siguen 8 clientes |
| Alta de Ana Prueba, DNI `30111222`, OSDE, afiliado `99` | `C009`, `activo` true | 9 clientes |
| Modificar el email de `C009` a `ana2@x.com` | El documento queda con ese email | El resto no cambia |
| Baja de `C009` | `activo` pasa a false | El documento sigue; siguen 9 clientes |

La cobertura válida es OSDE, Swiss Medical, PAMI, IOMA, Galeno o Sin cobertura. El número de afiliado va vacío solo con Sin cobertura.

## Consulta 14

Registro de una venta nueva Completada en MongoDB [P18, p. 6]. El llamador manda `id_producto` y `cantidad`. El servicio copia `precio_unit` del producto y el total es la suma. No recibe la fecha: usa `hoy()`.

Antes, con la carga recién hecha: 16 ventas; `L005` en `S001` con 40 unidades y vencimiento 2026-11-30; `L015` en `S001` con 100 unidades y vencimiento 2027-06-30; `RC003` vigente, 2 de 3, próxima 2026-10-01; `RC004` vigente, 1 de 3, próxima 2026-10-20. El precio de `PRD003` es 9800.

| Caso | Resultado | Lotes y receta |
|---|---|---|
| 200 unidades de `PRD003` en `S001`, con `F001` y `RC004` | Rechazo: no hay stock vigente de `PRD003` en `S001` | Sin cambios. Siguen 16 ventas |
| 1 unidad de `PRD003` con `F007` | Rechazo: el farmacéutico no pertenece a una sucursal de tipo Farmacia | Sin cambios. `F007` es de la droguería |
| 50 unidades de `PRD003`, `F001`, `C006`, `RC003`, obra social | `V017`, total 490000, Completada, fecha 2026-11-07, ítem `D023` | 40 de `L005` y 10 de `L015`. `L005` queda en 0 y `L015` en 90. `RC003` pasa a Completada, 3 de 3, sin próxima dispensa |
| 50 unidades de `PRD003`, `F001`, `C006`, `RC004`, obra social | `V018`, ítem `D024`, las 50 de `L015` | `L015` queda en 40. `RC004` sigue Vigente, 2 de 3, y la próxima dispensa pasa al 2026-12-07, treinta días después del 2026-11-07 |

## Consulta 15

Completa una venta que ya está Pendiente [P18, p. 6]. Descuenta por FEFO en la sucursal del farmacéutico, actualiza la receta y, solo si todo alcanzó, la pasa a Completada. `fecha` pasa a ser el día de la entrega, que es cuando computa ingresos. La reserva queda en `fecha_registro`. Los precios no se recalculan.

Antes: `V011` Pendiente, fecha 2026-10-12, una unidad de `PRD007` a 4800, receta `RC006`. `L014` en `S004` tiene 45 unidades. `RC006` es simple, vigente, 0 de 1. `V012` está Pendiente y `S003` no tiene lotes de sus productos. `V003` ya está Completada.

| Caso | Resultado | Después |
|---|---|---|
| `V003` | Rechazo: la venta está Completada; solo se completa una Pendiente | Ningún lote cambia |
| `V012` | Rechazo: no hay stock vigente de `PRD002` en `S003` | Sigue Pendiente, con su fecha y sus ítems. Ningún lote cambia |
| `V011` | Completada, fecha 2026-11-07, `fecha_registro` 2026-10-12, el ítem `D014` sale de `L014` | `L014` pasa de 45 a 44. `RC006` queda Completada, 1 de 1, sin próxima dispensa |

En una venta Completada, `fecha` es el día que usan las consultas 3, 5, 11 y 12. Una reserva de octubre completada en noviembre entra en noviembre. `fecha_registro` solo conserva el día de la reserva.

## Consistencia de la 14 y la 15

Las dos tienen que quedar integradas: si el descuento falla, no pueden quedar una venta ni una receta modificadas [P18, p. 7]. Comparten `descontar(id_sucursal, items)`.

El plan FEFO lee los lotes con `vencimiento` mayor o igual a `hoy()`, ordenados por `{vencimiento: 1, _id: 1}`. El día de vencimiento todavía se vende. El `sort` de MongoDB no es estable, y `_id` es el id del lote, así que dos lotes que vencen el mismo día salen siempre en el mismo orden. Si dos ítems piden el mismo producto, el plan descuenta en memoria lo ya asignado para no usar dos veces las mismas unidades.

Si el plan no alcanza, se rechaza antes de escribir. Si alcanza, cada lote se baja con la condición `unidades` mayor o igual a lo que se toma. Si un lote ya no alcanza, se reponen los que sí se habían bajado y se rechaza.

La receta se actualiza con la condición de que `dispensas_realizadas` siga valiendo lo que se leyó. En un tratamiento prolongado, si todavía quedan dispensas, la próxima es la fecha de la dispensa más 30 días; al llegar a las autorizadas pasa a Completada y la próxima queda vacía. Una receta simple se completa en esa única dispensa [P18, p. 5]. Si la condición no coincide, se reponen los lotes y no se graba ni se completa la venta.

La 14 inserta la venta después del descuento y de la receta. Si no puede asignar el id, repone las dos cosas: no queda la venta. La 15 pasa a Completada con la condición `estado: "Pendiente"`. Una segunda llamada no encuentra la venta en ese estado, así que no vuelve a descontar. No hace falta un campo `stock_descontado`. Si esa condición no coincide, se reponen los lotes y la receta.

No se usan transacciones de varios documentos. En MongoDB esas transacciones piden un replica set, y este entorno es una sola instancia. La estrategia es el orden de las operaciones, la actualización condicional y la reposición.

Cada ítem descontado guarda `lotes: [{id_lote, unidades}]`. Las ventas que vienen del CSV no lo traen.

Si la proyección a Neo4j falla, Mongo ya confirmó. La consulta responde bien y agrega `aviso_grafo`: el grafo quedó pendiente. `reconstruir()` lo rehace desde Mongo. Hoy las cuatro funciones de `src/grafo.py` están vacías, así que los casos que entran muestran ese aviso.

## Limitación y supuestos

`compose.yaml` fija `GLIBC_TUNABLES=glibc.pthread.rseq=1` en Mongo `8.3.11`. La imagen trae `rseq=0` y, en kernels 6.19 a 7.0.13, el proceso se corta al iniciar si glibc también usa rseq. Pasa en Docker Desktop para Mac. Con `rseq=1` glibc se queda el registro, TCMalloc no lo usa y Mongo arranca. El log muestra un aviso de rendimiento: es el efecto esperado y con estos datos no importa. En Codespaces, con kernel 6.8, arranca igual sin la variable. Queda fija para que el mismo archivo sirva en todas las máquinas. El 2026-11-07 el tag `neo4j:5.26.33` no estaba en Docker Hub; el compose usa `neo4j:5.26.32`, el último parche publicado de esa serie.

Supuestos de esta parte: ciudad y provincia se modifican como datos de contacto, y la consulta 15 es el paso de una venta Pendiente a Completada. Ese paso mueve `fecha` al día de la entrega y guarda la reserva en `fecha_registro`.
