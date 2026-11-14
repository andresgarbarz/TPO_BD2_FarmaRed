# Consultas Q01, Q05, Q07, Q08, Q09 y Q11

Implementación y verificación: 10 de noviembre de 2026, MongoDB `8.3.11`, PyMongo `4.15.3` y Python `3.11`. Las seis consultas usan MongoDB y exponen `ejecutar()` sin parámetros, con retorno `list[dict]`; sin coincidencias devuelven `[]`. La consigna está en [P18, p. 6].

Actualización del 14 de noviembre de 2026: las quince consultas y el grafo están integrados. Los resultados del 10 de noviembre de este documento se conservan como historial. La revisión completa ejecutó 25 pruebas; ver [Q04/Q06/Q12 e integración](informe-consultas-restantes.md).

## Modelo y relaciones

Se conserva el modelo del grupo: los ítems están embebidos en `ventas.items`; las entidades compartidas se referencian por id y se resuelven con `$lookup` contra `_id`. Embeber datos que se leen con su documento principal y referenciar datos compartidos aplica los criterios de modelado de la materia. [T14, pp. 2–8, 16–20]

La carga valida las referencias de los CSV. Los ensambles de estas consultas presuponen ese contrato; no reconstruyen referencias inválidas insertadas manualmente. El informe debe explicar cómo se cruzan entidades, además de mostrar código y resultados. [P18, pp. 6–7]

## Q01 — productos activos con proveedor completo

Código: [q01.py](../src/consultas/q01.py). Pipeline: seleccionar `productos.activo = true`, ensamblar `productos.id_proveedor = proveedores._id`, desplegar el proveedor y ordenar por id de producto.

Cada resultado conserva el producto y agrega el subdocumento `proveedor` con todos sus campos. No se filtra por actividad del proveedor. El ensamble aplica `$lookup`, presentado como left outer join en la materia. [P18, p. 6; T14, pp. 21–24]

Ejemplo resumido: salen once productos, `PRD001` a `PRD011`. Para `PRD001`, el proveedor completo es:

```python
{
    '_id': 'PRV001', 'id_proveedor': 'PRV001',
    'razon_social': 'Laboratorios Andinos S.A.', 'cuit': '30-71234567-1',
    'tipo': 'Laboratorio', 'ciudad': 'Buenos Aires',
    'provincia': 'Buenos Aires', 'telefono': '1143001100', 'activo': True
}
```

## Q05 — farmacéuticos activos y ventas de los últimos 60 días

Código: [q05.py](../src/consultas/q05.py). Se parte de los farmacéuticos activos y se ensamblan sus ventas con filtro de fecha y estado. Un subpipeline cuenta las ventas y la ausencia de coincidencias se convierte en cero. Devuelve `id_farmaceutico`, `nombre`, `apellido`, `matricula` y `cantidad_ventas`.

Conservar el lado de farmacéuticos permite mostrar los ceros. Se cuentan documentos de venta, no unidades ni ítems. Pendientes sí; anuladas no. Se incluye `F007`, que trabaja en la droguería, porque el enunciado no limita el tipo de sucursal. [P18, p. 6; T14, p. 23; T15, p. 33]

La consigna no precisa la inclusión de los límites: se decidió contar 60 días incluyendo hoy, desde `hoy() - 59 días` inclusive hasta mañana exclusivo. La revisión corrigió el rango anterior, que incluía 61 fechas. `hoy()` se evalúa una vez y usa Argentina. No se fija una fecha en el código de producción. [P18, p. 6]

El 2026-11-10 el corte es 2026-09-12. Resultado resumido:

| Farmacéutico | Ventas |
|---|---|
| F001 | 1 |
| F002 | 2 |
| F003 | 1 |
| F005 | 3 |
| F006 | 1 |
| F007 | 0 |

`F004` no aparece por estar inactivo. Ejemplo de una fila completa:

```python
{'id_farmaceutico': 'F007', 'nombre': 'Romina', 'apellido': 'Acuña',
 'matricula': 'MN-18401', 'cantidad_ventas': 0}
```

## Q07 — cinco productos más vendidos por unidades

Código: [q07.py](../src/consultas/q07.py). Pipeline: seleccionar Completada, desplegar `items`, agrupar por `items.id_producto`, sumar `items.cantidad`, ordenar, limitar a cinco y resolver el nombre del producto.

El patrón de `$unwind`, `$group`, `$sum`, `$sort` y `$limit` se usa en el ejercicio de e-commerce. No se filtra por fecha ni por actividad actual del producto. El desempate por id ascendente es una decisión del grupo. [P11A, pp. 2–3; P18, p. 6]

Resultado:

| id_producto | nombre | unidades_vendidas |
|---|---|---|
| PRD005 | Metformina 850mg x60 | 6 |
| PRD011 | Loratadina 10mg x10 | 5 |
| PRD001 | Paracetamol 500mg x30 | 4 |
| PRD004 | Losartán 50mg x30 | 3 |
| PRD009 | Levotiroxina 100mcg x50 | 2 |

## Q08 — lotes con menos de 50 unidades

Código: [q08.py](../src/consultas/q08.py). Se filtra `stock_lotes.unidades < 50`, se resuelve el producto y la sucursal y, desde `producto.id_proveedor`, el proveedor. Cada lote conserva sus campos y agrega los subdocumentos `producto`, `sucursal` y `proveedor`; la salida se ordena por id de lote. [P18, pp. 3–4, 6; T14, pp. 21–24]

Salen nueve lotes: `L002`, `L003`, `L005`, `L007`, `L010`, `L011`, `L012`, `L014` y `L018`. Un resumen de `L018` es: 15 unidades de Alcohol en gel 250ml, en Farmacia Belgrano, proveedor DroguMed S.R.L. Está vencido y su producto está inactivo: sigue incluido porque esta lectura no impone esos filtros.

## Q09 — ventas libres con total menor a $5.000

Código: [q09.py](../src/consultas/q09.py). Se usa `find` con `tipo = "Venta libre"`, `total < 5000` y `estado != "Anulada"`, ordenado por id. Devuelve los documentos completos, incluidos sus ítems. La igualdad, los comparadores y su AND implícito están en la guía de MongoDB. [P10A, p. 3; P18, p. 6]

Resultado resumido: `V013`, total $4.400; `V014`, total $4.600. Ambas Completada. Una pendiente que cumpla el tipo y el importe también pertenece al resultado; una venta de exactamente $5.000 queda fuera.

## Q11 — vista agregada de ingresos del mes

Código: [q11.py](../src/consultas/q11.py). La carga llama a `crear_vista()`, que crea o actualiza `ingresos_mensuales_farmaceutico` sobre `ventas`. Su pipeline selecciona Completada, agrupa por farmacéutico, año y mes de `fecha` y suma `total`. `ejecutar()` filtra esa vista por el año y mes de `hoy()`, resuelve nombre, apellido y matrícula, y ordena por id.

La materia presenta la creación y consulta de vistas y la agregación por grupos. La decisión de usar una vista mensual general más la selección del mes actual permite cambiar de período sin recrearla. El ingreso sale del total histórico de la venta; pendientes y anuladas no computan. Un farmacéutico hoy inactivo conserva sus ingresos históricos. [T13, pp. 50–52; T15, p. 33; P18, pp. 4–6]

Las fechas del proyecto representan días civiles a medianoche, construidos con año, mes y día. Al extraer el período se conservan esos componentes, sin convertir otra vez la zona horaria. El mes actual sí se determina con `hoy()` en Argentina. Se usa `fecha`, no `fecha_registro`, conforme al contrato de Q15.

**Complemento del agente (no consta en el material cargado):** se usan `$year` y `$month` para extraer el período. La vista estándar calcula los resultados al consultarse, sin persistir una copia de los ingresos. Manual oficial de [`$year`](https://www.mongodb.com/docs/manual/reference/operator/aggregation/year/), [`$month`](https://www.mongodb.com/docs/manual/reference/operator/aggregation/month/) y [vistas](https://www.mongodb.com/docs/manual/core/views/).

El 2026-11-10, con los CSV intactos, el resultado real es `[]`: no hay ventas de noviembre. Como control con reloj de prueba en octubre de 2026, se obtuvieron `F001: 4400`, `F002: 7800`, `F003: 7100`, `F005: 4600`. Una fila de ese control:

```python
{'id_farmaceutico': 'F001', 'nombre': 'Mariana', 'apellido': 'Quiroga',
 'matricula': 'MN-18041', 'anio': 2026, 'mes': 10, 'ingresos_totales': 4400}
```

También se ejecutó Q15 sobre `V011` en una base de prueba con reloj en 2026-11-10: pasó a Completada, `fecha` pasó a noviembre y `fecha_registro` conservó 2026-10-12. Q11 mostró $4.800 para `F006` sin recrear la vista. Una segunda ejecución rechazada de Q15 no duplicó el ingreso.

## Verificación realizada

Se inició MongoDB `8.3.11` en un contenedor aislado (`farmared-consultas-test`, `127.0.0.1:27018`), se ejecutó el cargador real y luego las seis consultas con el reloj del sistema. Los resultados coincidieron con los controles anteriores. El aviso de grafo pendiente es esperado: esa parte sigue sin implementar y estas lecturas usan MongoDB.

Se ejecutaron **17 pruebas de integración, todas correctas**, en [tests/test_consultas.py](../tests/test_consultas.py). Usan los nueve CSV completos y una base temporal propia. Cubren los seis resultados, proveedor inactivo, referencias, límites de stock e importe, vencidos, ceros, estados, conteo de ventas frente a ítems, empates, producto inactivo, mes vacío, límites de mes/año, farmacéutico inactivo, cambio de reloj sin recrear vista, repetición de la carga y preparación de la vista e integración con Q15. La regresión de Q05 carga una venta por fecha durante 61 días y exige contar exactamente 60. El verificador de datasets también pasó.

No se agregaron dependencias ni índices. No se implementaron el grafo ni las otras seis consultas pendientes. Los registros adicionales persistentes del grupo y los diagramas siguen abiertos; los casos de prueba no reemplazan los diez registros propios por colección/tabla exigidos para la entrega. [P18, pp. 1, 6–7]
