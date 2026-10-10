"""RAGSystem: recuperador híbrido (BM25 + vectorial) sobre Pinecone.

Combina dos formas de buscar, que se complementan:

- **Búsqueda vectorial (semántica)**: Pinecone compara el embedding de la
  consulta con los embeddings de los chunks. Encuentra textos con el mismo
  *significado* aunque usen otras palabras ("espera exponencial" ->
  `backoff_factor`).
- **Búsqueda léxica (BM25)**: puntúa los chunks por coincidencia de
  *palabras exactas*, ponderando las poco frecuentes. Es muy buena para
  términos técnicos, códigos y nombres propios ("E4021", `run_in_executor`),
  donde el embedding suele "diluir" el término.

`EnsembleRetriever` fusiona ambos rankings con Reciprocal Rank Fusion (RRF).

BM25 necesita el corpus en memoria. Como el texto original está guardado en
la metadata de Pinecone, lo reconstruimos desde ahí al iniciar: no hace falta
ninguna base de datos adicional ni copia local de los documentos.
"""

import logging
import re
import unicodedata

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore

try:  # LangChain 1.x: los retrievers "clásicos" viven en langchain-classic
    from langchain_classic.retrievers import EnsembleRetriever
except ImportError:  # LangChain 0.x
    from langchain.retrievers import EnsembleRetriever

from config import TOP_K, Settings, get_settings
from pinecone_setup import get_field, get_pinecone_client

logger = logging.getLogger("rag_system")

TEXT_KEY = "text"
FETCH_BATCH_SIZE = 100
MODES = ("hybrid", "vector", "bm25")

# Palabras muy comunes en español: no aportan señal léxica.
STOPWORDS = frozenset(
    "a al como con de del el en es la las lo los o para por que se su un una y".split()
)


def tokenize(texto: str) -> list[str]:
    """Tokenizador para BM25, pensado para texto técnico en español.

    - Pasa a minúsculas y quita acentos ("Cómo" == "como").
    - Conserva identificadores completos (`e4021`, `backoff_factor`) y además
      agrega sus partes (`backoff`, `factor`), así una consulta por una sola
      parte también encuentra el identificador.
    - Descarta stopwords.
    """
    normalizado = unicodedata.normalize("NFKD", texto.lower())
    sin_acentos = "".join(c for c in normalizado if not unicodedata.combining(c))
    tokens: list[str] = []
    for token in re.findall(r"\w+", sin_acentos):
        if token in STOPWORDS:
            continue
        tokens.append(token)
        if "_" in token:
            tokens.extend(parte for parte in token.split("_") if parte)
    return tokens


class LexicalRetriever(BM25Retriever):
    """BM25Retriever que descarta los chunks con puntaje 0.

    El `BM25Retriever` estándar siempre devuelve los `k` mejores, aunque no
    compartan ni una palabra con la consulta; esos resultados arbitrarios
    contaminarían la fusión con la búsqueda vectorial.
    """

    def _get_relevant_documents(self, query: str, *, run_manager) -> list[Document]:
        puntajes = self.vectorizer.get_scores(self.preprocess_func(query))
        ranking = sorted(zip(puntajes, self.docs), key=lambda par: par[0], reverse=True)
        return [doc for puntaje, doc in ranking[: self.k] if puntaje > 0]


def load_corpus_from_pinecone(
    index, namespace: str, text_key: str = TEXT_KEY
) -> list[Document]:
    """Reconstruye el corpus completo de un namespace leyendo Pinecone
    (`list` para obtener los ids, `fetch` para traer metadata y texto)."""
    documentos: list[Document] = []
    for pagina_ids in index.list(namespace=namespace):
        ids = list(pagina_ids)
        for inicio in range(0, len(ids), FETCH_BATCH_SIZE):
            respuesta = index.fetch(
                ids=ids[inicio:inicio + FETCH_BATCH_SIZE], namespace=namespace
            )
            for vector_id, vector in (get_field(respuesta, "vectors") or {}).items():
                metadata = dict(get_field(vector, "metadata") or {})
                texto = metadata.pop(text_key, None)
                if texto is None:
                    continue
                metadata.setdefault("chunk_id", vector_id)
                documentos.append(
                    Document(id=vector_id, page_content=texto, metadata=metadata)
                )
    documentos.sort(key=lambda d: d.id)  # orden estable entre ejecuciones
    return documentos


class RAGSystem:
    """Encapsula el recuperador híbrido.

    Uso:
        rag = RAGSystem()
        docs = rag.retrieve("¿Qué significa el error E4021?")   # top-5 híbrido
        docs = rag.retrieve("...", category="errores")           # filtrando por metadata
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        index=None,
        embeddings=None,
        k: int = TOP_K,
        weights: tuple[float, float] = (0.5, 0.5),
    ):
        """`weights` = (peso BM25, peso vectorial) para la fusión RRF.
        `index` y `embeddings` se pueden inyectar (tests); si no, se crean."""
        self.settings = settings or get_settings()
        self.k = k
        self.weights = list(weights)

        if index is None:
            pc = get_pinecone_client(self.settings)
            index = pc.Index(self.settings.index_name)
        if embeddings is None:
            embeddings = OpenAIEmbeddings(
                model=self.settings.embedding_model,
                api_key=self.settings.openai_api_key,
            )

        self.index = index
        self.corpus = load_corpus_from_pinecone(index, self.settings.namespace)
        if not self.corpus:
            raise RuntimeError(
                f"El namespace '{self.settings.namespace}' del índice "
                f"'{self.settings.index_name}' está vacío. Corré primero "
                "`python ingest.py`."
            )
        logger.info(
            "Corpus cargado desde Pinecone: %d chunks de %d documentos.",
            len(self.corpus),
            len(self.chunks_per_doc),
        )

        self.vector_store = PineconeVectorStore(
            index=index,
            embedding=embeddings,
            text_key=TEXT_KEY,
            namespace=self.settings.namespace,
        )
        self._cache: dict[str | None, dict] = {}

    @property
    def chunks_per_doc(self) -> dict[str, int]:
        conteo: dict[str, int] = {}
        for doc in self.corpus:
            doc_id = doc.metadata.get("doc_id")
            conteo[doc_id] = conteo.get(doc_id, 0) + 1
        return conteo

    @property
    def categories(self) -> list[str]:
        return sorted({d.metadata.get("category") for d in self.corpus})

    def _retrievers(self, category: str | None) -> dict:
        """Arma (y cachea) los tres recuperadores para una categoría dada."""
        if category in self._cache:
            return self._cache[category]

        corpus = self.corpus
        search_kwargs: dict = {"k": self.k}
        if category is not None:
            corpus = [d for d in self.corpus if d.metadata.get("category") == category]
            if not corpus:
                raise ValueError(
                    f"No hay chunks con la categoría '{category}'. "
                    f"Categorías disponibles: {self.categories}"
                )
            search_kwargs["filter"] = {"category": {"$eq": category}}

        vectorial = self.vector_store.as_retriever(search_kwargs=search_kwargs)
        lexico = LexicalRetriever.from_documents(
            corpus, preprocess_func=tokenize, k=self.k
        )
        # id_key="chunk_id": el mismo chunk que aparece en ambos rankings se
        # fusiona (y suma puntaje) por id, no por coincidencia de texto.
        hibrido = EnsembleRetriever(
            retrievers=[lexico, vectorial],
            weights=self.weights,
            id_key="chunk_id",
        )
        self._cache[category] = {"hybrid": hibrido, "vector": vectorial, "bm25": lexico}
        return self._cache[category]

    def retrieve(
        self, query: str, *, mode: str = "hybrid", category: str | None = None
    ) -> list[Document]:
        """Devuelve los top-k chunks para la consulta.

        mode: "hybrid" (BM25 + vectorial, el sistema real), o "vector" /
        "bm25" para comparar cada mitad por separado (lo usa evaluate.py).
        category: si se indica, restringe la búsqueda a esa categoría de metadata.
        """
        if mode not in MODES:
            raise ValueError(f"mode debe ser uno de {MODES}, no '{mode}'.")
        retriever = self._retrievers(category)[mode]
        return retriever.invoke(query)[: self.k]
