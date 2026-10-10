"""Setup de Pinecone: verifica si el índice existe y lo crea (Serverless) si hace falta.

Se puede correr como script (`python pinecone_setup.py`) o importar
`ensure_index()` desde otros módulos (lo hace `ingest.py`).
"""

import logging
import time

from pinecone import Pinecone, ServerlessSpec

from config import Settings, get_settings

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("pinecone_setup")

READY_TIMEOUT_SECONDS = 180


def get_field(obj, key):
    """Lee `key` de un objeto de respuesta del SDK de Pinecone, que según la
    versión se accede como atributo o como diccionario."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def get_pinecone_client(settings: Settings) -> Pinecone:
    return Pinecone(api_key=settings.pinecone_api_key)


def ensure_index(pc: Pinecone, settings: Settings) -> None:
    """Crea el índice Serverless si no existe. Si ya existe, verifica que su
    dimensión coincida con la de los embeddings (error común: subir vectores
    de 1536 dimensiones a un índice creado con 512 o 768)."""
    existentes = pc.list_indexes().names()

    if settings.index_name in existentes:
        descripcion = pc.describe_index(settings.index_name)
        dimension_indice = get_field(descripcion, "dimension")
        if dimension_indice != settings.dimension:
            raise RuntimeError(
                f"El índice '{settings.index_name}' ya existe con dimensión "
                f"{dimension_indice}, pero los embeddings "
                f"('{settings.embedding_model}') tienen dimensión "
                f"{settings.dimension}. Usá otro INDEX_NAME o borrá el índice "
                "desde la consola de Pinecone y volvé a correr el setup."
            )
        logger.info(
            "El índice '%s' ya existe (dimensión %s). No se crea de nuevo.",
            settings.index_name,
            dimension_indice,
        )
        return

    logger.info(
        "Creando índice Serverless '%s' (dimensión=%d, métrica=cosine, %s/%s)...",
        settings.index_name,
        settings.dimension,
        settings.cloud,
        settings.region,
    )
    pc.create_index(
        name=settings.index_name,
        dimension=settings.dimension,
        metric="cosine",
        spec=ServerlessSpec(cloud=settings.cloud, region=settings.region),
    )
    _wait_until_ready(pc, settings.index_name)
    logger.info("Índice '%s' listo.", settings.index_name)


def _wait_until_ready(pc: Pinecone, index_name: str) -> None:
    """La creación del índice es asíncrona: esperamos a que quede 'ready'."""
    inicio = time.time()
    while time.time() - inicio < READY_TIMEOUT_SECONDS:
        status = get_field(pc.describe_index(index_name), "status")
        if status is not None and get_field(status, "ready"):
            return
        time.sleep(2)
    raise TimeoutError(
        f"El índice '{index_name}' no estuvo listo después de "
        f"{READY_TIMEOUT_SECONDS} segundos."
    )


def namespace_vector_count(index, namespace: str, *, attempts: int = 5) -> int:
    """Cantidad de vectores que hay actualmente en un namespace.

    Un índice recién creado puede figurar como 'ready' y aun así rechazar
    conexiones unos segundos (propagación de DNS), así que reintentamos."""
    for intento in range(1, attempts + 1):
        try:
            stats = index.describe_index_stats()
            break
        except Exception as error:  # el SDK lanza distintos tipos según el fallo
            if intento == attempts:
                raise
            logger.info(
                "El índice todavía no responde (%s). Reintentando en 3 s (%d/%d)...",
                type(error).__name__,
                intento,
                attempts,
            )
            time.sleep(3)
    namespaces = get_field(stats, "namespaces") or {}
    resumen = namespaces.get(namespace)
    if resumen is None:
        return 0
    return int(get_field(resumen, "vector_count") or 0)


if __name__ == "__main__":
    try:
        configuracion = get_settings()
        cliente = get_pinecone_client(configuracion)
        ensure_index(cliente, configuracion)
        indice = cliente.Index(configuracion.index_name)
        total = namespace_vector_count(indice, configuracion.namespace)
    except (RuntimeError, TimeoutError) as error:
        raise SystemExit(f"Error: {error}")
    logger.info(
        "Namespace '%s': %d vectores actualmente.", configuracion.namespace, total
    )
