# Q04, Q06 y Q12 — decisiones y ejemplos

Revisión de integración: 14 de noviembre de 2026. MongoDB 8.3.11 y los nueve CSV
provistos, sin extras. Las tres funciones no reciben argumentos y devuelven
`list[dict]`. La consigna está en [P18, p. 6].

## Q04: clientes con más de una receta

Agrupa `recetas` por `id_cliente`, cuenta documentos y conserva cantidades
mayores que uno. Resuelve el cliente con `$lookup` contra `clientes._id` y
devuelve id, nombre, apellido, DNI y cantidad. No filtra estados de recetas ni
actividad del cliente: la consigna dice recetas registradas. [P18, p. 6]

Resultado: `C001: 2`, `C002: 2`, `C006: 2`.

## Q06: dispensas atrasadas

Filtra recetas de `Tratamiento prolongado`, estado `Vigente`, con
`proxima_dispensa` de tipo fecha y estrictamente anterior a `hoy()`. Resuelve
todos los datos del cliente con `$lookup`. No filtra clientes inactivos.
Las fechas nulas, ausentes, de hoy y futuras quedan fuera. [P18, p. 6]

El 2026-11-14 devuelve `RC002` (cliente `C003`, próxima dispensa 2026-09-15),
`RC003` (`C006`, 2026-10-01) y `RC004` (`C006`, 2026-10-20).

## Q12: clientes sin ventas recientes

Parte de todos los clientes, busca como máximo una venta reciente por cliente y
conserva aquellos sin coincidencias. Incluye clientes inactivos y clientes que
nunca compraron. Considera ventas de cualquier estado, incluidas las anuladas:
Q12 no las excluye, a diferencia de otras consultas. Usa `ventas.fecha`, igual
que Q05 y Q11. [P18, p. 6]

**Decisión del proyecto:** “último año” se interpreta como 365 días incluyendo
hoy: desde `hoy() - 364 días` inclusivo hasta mañana exclusivo. No es una
definición explícita de la cátedra ni un año calendario; en años bisiestos se
mantiene la ventana de 365 días. Las fechas de producción salen del sistema.

El 2026-11-14 devuelve `C004` (última venta 2025-09-18) y `C008` (sin ventas).

## Verificación de la integración

Se resolvió el conflicto del cargador conservando la preparación de la vista
mensual de Q11 y la proyección completa a Neo4j. Se ejecutó el cargador real dos
veces en contenedores exclusivos de revisión, sin modificar bases preexistentes.

La suite contiene 22 pruebas MongoDB y tres de grafo. Las nuevas pruebas
MongoDB cubren Q04, Q06 y Q12 con el dataset y con límites de fechas, nulos,
estados y clientes inactivos. La prueba MongoDB de Q15 aísla la proyección para
no escribir en un Neo4j ajeno a la prueba.

Las pruebas Neo4j verifican 58 nodos y 96 relaciones tras reconstrucciones,
Q02/Q03/Q10, historial con farmacéutico inactivo y reasignado, relaciones sin
duplicados, ítems repetidos con precios distintos, referencias inválidas,
proyección de Q13/Q14/Q15, consumo FEFO y rechazo sin cambios por falta de stock.
Requieren una instancia descartable indicada por `FARMARED_TEST_NEO4J_URI`.

Quedan los diez registros adicionales por colección/tabla, el diagrama de
colecciones y el informe PDF integrado. Los casos temporales de prueba no
reemplazan los registros propios exigidos. [P18, pp. 1, 6–7]
