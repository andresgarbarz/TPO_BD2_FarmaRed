"""Proyección del grafo. Vacía hasta que se implemente Neo4j.

La carga llama a reconstruir al final. La consulta 13 llama a upsert_cliente.
Las consultas 14 y 15 llaman a upsert_venta y, si hubo receta, a upsert_receta.
Reciben el documento tal como quedó en Mongo.

Si alguna falla, la escritura en Mongo ya está confirmada: la consulta no
devuelve error y avisa que el grafo quedó pendiente. reconstruir lo rehace.
"""


class GrafoPendiente(Exception):
    """Neo4j todavía no está implementado, o la proyección no se pudo aplicar."""


def reconstruir() -> None:
    """Rehace el grafo completo desde Mongo."""
    raise GrafoPendiente("el grafo quedó pendiente")


def upsert_cliente(documento: dict) -> None:
    """Crea o actualiza el nodo del cliente."""
    raise GrafoPendiente("el grafo quedó pendiente")


def upsert_venta(documento: dict) -> None:
    """Crea o actualiza la venta y sus relaciones."""
    raise GrafoPendiente("el grafo quedó pendiente")


def upsert_receta(documento: dict) -> None:
    """Crea o actualiza la receta y su relación con el cliente."""
    raise GrafoPendiente("el grafo quedó pendiente")


def proyectar(funcion, *args) -> str | None:
    """Ejecuta una proyección. Si falla, devuelve el aviso y no propaga."""
    try:
        funcion(*args)
    except Exception:
        return "el grafo quedó pendiente"
    return None
