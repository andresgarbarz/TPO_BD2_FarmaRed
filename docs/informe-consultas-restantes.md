# Q04, Q06 y Q12 — decisiones y ejemplos

Revisión: 15 de noviembre de 2026. MongoDB 8.3.11, los nueve CSV de la cátedra
y `datasets/extra/`. Las tres funciones no reciben argumentos y devuelven
`list[dict]`. La consigna está en [P18, p. 6]. `hoy()` ese día fue 2026-11-15.

## Q04: clientes con más de una receta

Agrupa `recetas` por `id_cliente`, cuenta documentos y conserva cantidades
mayores que uno. Resuelve el cliente con `$lookup` contra `clientes._id` y
devuelve id, nombre, apellido, DNI y cantidad. No filtra estados de recetas ni
actividad del cliente: la consigna dice recetas registradas. [P18, p. 6]

Resultado: `C001: 2`, `C002: 2`, `C006: 2`, `C011: 2` (Julián Álvarez) y `C018: 2` (Ángel Di María).

## Q06: dispensas atrasadas

Filtra recetas de `Tratamiento prolongado`, estado `Vigente`, con
`proxima_dispensa` de tipo fecha y estrictamente anterior a `hoy()`. Resuelve
todos los datos del cliente con `$lookup`. No filtra clientes inactivos.
Las fechas nulas, ausentes, de hoy y futuras quedan fuera. [P18, p. 6]

El 2026-11-15 devuelve `RC002` (cliente `C003`, próxima dispensa 2026-09-15),
`RC003` (`C006`, 2026-10-01), `RC004` (`C006`, 2026-10-20) y `RC013` (`C017`,
Nicolás Otamendi, 2026-11-01). `RC014`, de `C018`, queda afuera: su próxima
dispensa es el 2026-12-01.

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

El 2026-11-15 la ventana empieza el 2025-11-16. Devuelve `C004` (última venta
2025-09-18), `C008` (sin ventas), `C009` (Lionel Messi, sin ventas), `C010`
(Emiliano Martínez, única venta el 2024-06-15), `C012` (Enzo Fernández, receta
vencida y sin ventas) y `C013` (Alexis Mac Allister, inactivo y sin ventas).
`C016` no entra: su única venta está Anulada y esta consulta igual la cuenta.

## Verificación de la integración

Se resolvió el conflicto del cargador conservando la preparación de la vista
mensual de Q11 y la proyección completa a Neo4j. Se ejecutó el cargador real dos
veces en contenedores exclusivos de revisión, sin modificar bases preexistentes.

El 15 de noviembre la suite completa, 48 pruebas, pasó. Las de MongoDB cubren
Q04, Q06 y Q12 con el dataset de la cátedra y con límites de fechas, nulos,
estados y clientes inactivos. La prueba MongoDB de Q15 aísla la proyección para
no escribir en un Neo4j ajeno a la prueba.

Las pruebas Neo4j cargan solo los CSV de la cátedra en una base temporal y
verifican 58 nodos y 96 relaciones tras reconstrucciones, Q02/Q03/Q10, historial
con farmacéutico inactivo y reasignado, relaciones sin duplicados, ítems
repetidos con precios distintos, referencias inválidas, proyección de
Q13/Q14/Q15, consumo FEFO y rechazo sin cambios por falta de stock. Requieren
una instancia descartable indicada por `FARMARED_TEST_NEO4J_URI`. La carga real,
con registros propios, deja 118 nodos y 163 relaciones.

Los registros propios están en `datasets/extra/`: al menos diez por colección,
con fechas recientes, stock bajo, lotes por vencer o vencidos, recetas vencidas,
clientes sin compras y ventas pendientes. Quedan el diagrama de colecciones y
el informe PDF integrado. [P18, pp. 1, 6–7]
