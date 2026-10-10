"""Pipeline de ingesta a Pinecone Serverless.

Flujo: cargar documentos (.md / .txt / .pdf) -> dividir en chunks -> generar
embeddings -> subir a Pinecone con metadata avanzada.

Decisiones de diseño:

- **El texto original va dentro de la metadata** (clave `text`). Así, al
  recuperar un vector, Pinecone ya nos devuelve el contenido y no hace falta
  consultar una base de datos relacional aparte. Es también el formato que
  espera `PineconeVectorStore` de LangChain (`text_key="text"`).
- **Metadata avanzada**: `source` (ruta del archivo), `doc_id` (id lógico del
  documento, usado por la evaluación), `page`, `category`, `tags`,
  `chunk_index` y `chunk_id`.
- **IDs determinísticos** (`<doc_id>::c000`): volver a subir el mismo
  documento sobrescribe los vectores en vez de duplicarlos (upsert idempotente).
- **Namespace**: todo el dataset se sube a un namespace propio, para que la
  búsqueda no se mezcle con otros datos del mismo índice.

Uso:
    python ingest.py            # ingesta si el namespace está vacío
    python ingest.py --force    # vuelve a subir todo (upsert)
    python ingest.py --reset    # borra el namespace y vuelve a indexar
"""

import argparse
import logging
import re
import time
from collections import defaultdict
from pathlib import Path

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from config import (
    CHUNK_OVERLAP_TOKENS,
    CHUNK_SIZE_TOKENS,
    DATA_DIR,
    Settings,
    get_settings,
)
from pinecone_setup import ensure_index, get_pinecone_client, namespace_vector_count

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("ingest")

SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf"}
UPSERT_BATCH_SIZE = 100
CONSISTENCY_TIMEOUT_SECONDS = 60

# Claves de metadata que se suben a Pinecone (además de `text`).
METADATA_KEYS = (
    "source",
    "doc_id",
    "page",
    "category",
    "tags",
    "chunk_index",
    "chunk_id",
)


# --------------------------------------------------------------------------
# 1. Carga de documentos
# --------------------------------------------------------------------------
def parse_front_matter(texto: str) -> tuple[dict, str]:
    """Separa el encabezado opcional (entre líneas `---`) del cuerpo.

    Formato esperado, una clave por línea:
        ---
        categoria: errores
        tags: errores, diagnostico
        ---
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", texto, re.DOTALL)
    if not match:
        return {}, texto
    meta = {}
    for linea in match.group(1).splitlines():
        if ":" in linea:
            clave, valor = linea.split(":", 1)
            meta[clave.strip().lower()] = valor.strip()
    return meta, texto[match.end():]


def _parse_tags(crudo: str) -> list[str]:
    return [t.strip() for t in crudo.split(",") if t.strip()]


def load_documents(data_dir: Path = DATA_DIR) -> list[Document]:
    """Lee todos los archivos soportados de `data_dir` (incluye subcarpetas).

    - `.md` / `.txt`: un Document por archivo (page=1). La categoría y los tags
      salen del encabezado; si no hay, la categoría es el nombre de la carpeta.
    - `.pdf`: un Document por página, con el número de página real.
    """
    documentos: list[Document] = []
    doc_ids_vistos: dict[str, str] = {}

    for ruta in sorted(data_dir.rglob("*")):
        if not ruta.is_file() or ruta.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        relativa = ruta.relative_to(data_dir).as_posix()
        doc_id = ruta.stem
        if doc_id in doc_ids_vistos:
            raise ValueError(
                f"Dos archivos comparten el mismo nombre base '{doc_id}': "
                f"{doc_ids_vistos[doc_id]} y {relativa}. Renombrá uno, porque "
                "el doc_id tiene que ser único."
            )
        doc_ids_vistos[doc_id] = relativa

        carpeta = ruta.parent.name if ruta.parent != data_dir else "general"

        if ruta.suffix.lower() == ".pdf":
            lector = PdfReader(str(ruta))
            for numero, pagina in enumerate(lector.pages, start=1):
                texto = (pagina.extract_text() or "").strip()
                if not texto:
                    continue
                documentos.append(
                    Document(
                        page_content=texto,
                        metadata={
                            "source": relativa,
                            "doc_id": doc_id,
                            "page": numero,
                            "category": carpeta,
                            "tags": [],
                        },
                    )
                )
        else:
            crudo = ruta.read_text(encoding="utf-8")
            encabezado, cuerpo = parse_front_matter(crudo)
            documentos.append(
                Document(
                    page_content=cuerpo.strip(),
                    metadata={
                        "source": relativa,
                        "doc_id": doc_id,
                        "page": 1,
                        "category": encabezado.get("categoria") or carpeta,
                        "tags": _parse_tags(encabezado.get("tags", "")),
                    },
                )
            )

    return documentos


# --------------------------------------------------------------------------
# 2. Chunking
# --------------------------------------------------------------------------
def split_documents(
    documentos: list[Document],
    chunk_size: int = CHUNK_SIZE_TOKENS,
    chunk_overlap: int = CHUNK_OVERLAP_TOKENS,
) -> list[Document]:
    """Divide en chunks midiendo en TOKENS (encoder de OpenAI), no en
    caracteres, y le asigna a cada chunk un id determinístico."""
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    chunks = splitter.split_documents(documentos)

    contador: dict[str, int] = defaultdict(int)
    for chunk in chunks:
        doc_id = chunk.metadata["doc_id"]
        indice = contador[doc_id]
        contador[doc_id] += 1
        chunk.metadata["chunk_index"] = indice
        chunk.metadata["chunk_id"] = f"{doc_id}::c{indice:03d}"
    return chunks


# --------------------------------------------------------------------------
# 3. Embeddings + subida a Pinecone
# --------------------------------------------------------------------------
def _build_metadata(chunk: Document) -> dict:
    """Metadata que se sube a Pinecone: campos escalares/listas de strings
    (Pinecone no admite valores nulos) + el texto original en `text`."""
    metadata = {k: chunk.metadata[k] for k in METADATA_KEYS}
    metadata["text"] = chunk.page_content
    return metadata


def upsert_chunks(
    index,
    embeddings,
    chunks: list[Document],
    namespace: str,
    expected_dimension: int,
) -> int:
    """Genera los embeddings por lotes y los sube con `index.upsert`."""
    subidos = 0
    for inicio in range(0, len(chunks), UPSERT_BATCH_SIZE):
        lote = chunks[inicio:inicio + UPSERT_BATCH_SIZE]
        vectores = embeddings.embed_documents([c.page_content for c in lote])

        if len(vectores[0]) != expected_dimension:
            raise RuntimeError(
                f"Los embeddings tienen dimensión {len(vectores[0])} pero el "
                f"índice espera {expected_dimension}. Revisá que el modelo de "
                "embeddings sea el mismo con el que se creó el índice."
            )

        index.upsert(
            vectors=[
                {
                    "id": chunk.metadata["chunk_id"],
                    "values": vector,
                    "metadata": _build_metadata(chunk),
                }
                for chunk, vector in zip(lote, vectores)
            ],
            namespace=namespace,
        )
        subidos += len(lote)
        logger.info("Subidos %d/%d chunks...", subidos, len(chunks))
    return subidos


def _wait_for_count(index, namespace: str, condicion, descripcion: str) -> None:
    """Pinecone es eventualmente consistente: las estadísticas pueden tardar
    unos segundos en reflejar un upsert o un borrado. Esperamos (con tope)."""
    inicio = time.time()
    while time.time() - inicio < CONSISTENCY_TIMEOUT_SECONDS:
        if condicion(namespace_vector_count(index, namespace)):
            return
        time.sleep(2)
    logger.warning(
        "Pasaron %ds y las estadísticas todavía no reflejan %s. Es normal que "
        "Pinecone tarde un poco; podés verificar con `python pinecone_setup.py`.",
        CONSISTENCY_TIMEOUT_SECONDS,
        descripcion,
    )


def run_ingestion(
    settings: Settings,
    *,
    data_dir: Path = DATA_DIR,
    force: bool = False,
    reset: bool = False,
    pc=None,
    embeddings=None,
) -> int:
    """Ejecuta el pipeline completo. Devuelve la cantidad de vectores que hay
    en el namespace al terminar.

    `pc` y `embeddings` se pueden inyectar (se usan en los tests); en uso
    normal se crean a partir de `settings`.
    """
    pc = pc or get_pinecone_client(settings)
    ensure_index(pc, settings)
    index = pc.Index(settings.index_name)

    existentes = namespace_vector_count(index, settings.namespace)

    if reset and existentes > 0:
        logger.info("--reset: borrando el namespace '%s'...", settings.namespace)
        index.delete(delete_all=True, namespace=settings.namespace)
        _wait_for_count(index, settings.namespace, lambda n: n == 0, "el borrado")
        existentes = 0

    if existentes > 0 and not force:
        logger.info(
            "El namespace '%s' ya tiene %d vectores — se omite la ingesta. "
            "Usá --force para volver a subir o --reset para empezar de cero.",
            settings.namespace,
            existentes,
        )
        return existentes

    documentos = load_documents(data_dir)
    if not documentos:
        raise RuntimeError(
            f"No se encontraron documentos (.md/.txt/.pdf) en {data_dir}."
        )

    chunks = split_documents(documentos)
    logger.info(
        "%d documento(s) -> %d chunk(s) (tamaño=%d tokens, overlap=%d).",
        len(documentos),
        len(chunks),
        CHUNK_SIZE_TOKENS,
        CHUNK_OVERLAP_TOKENS,
    )

    embeddings = embeddings or OpenAIEmbeddings(
        model=settings.embedding_model, api_key=settings.openai_api_key
    )
    upsert_chunks(
        index, embeddings, chunks, settings.namespace, settings.dimension
    )

    total = len(chunks)
    _wait_for_count(
        index,
        settings.namespace,
        lambda n: n >= total,
        f"los {total} vectores subidos",
    )
    logger.info(
        "Ingesta completa: %d vectores en el namespace '%s' del índice '%s'.",
        namespace_vector_count(index, settings.namespace),
        settings.namespace,
        settings.index_name,
    )
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingesta de documentos a Pinecone.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Volver a subir los documentos aunque el namespace ya tenga datos.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Borrar el namespace antes de indexar (útil si borraste documentos).",
    )
    args = parser.parse_args()
    try:
        run_ingestion(get_settings(), force=args.force, reset=args.reset)
    except (RuntimeError, ValueError) as error:
        raise SystemExit(f"Error: {error}")


if __name__ == "__main__":
    main()
