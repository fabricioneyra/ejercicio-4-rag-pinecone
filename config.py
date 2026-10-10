"""Configuración central: variables de entorno y constantes del proyecto.

Las API keys NUNCA van en el código: se leen del archivo `.env` (que está en
`.gitignore`). `get_settings()` valida upfront que estén todas y falla con un
mensaje claro, en vez de dejar que el error aparezca recién en medio de una
llamada a la API (mismo criterio que usamos con `LLMConfig` en el Ejercicio 1).
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
GOLDEN_SET_PATH = BASE_DIR / "golden_set.json"

# Modelo de embeddings: se usa SIEMPRE el mismo para indexar y para consultar.
# `text-embedding-3-small` devuelve vectores de 1536 dimensiones, y el índice
# de Pinecone tiene que estar creado con esa misma dimensión (error común #1:
# "Mismatch de dimensiones").
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536

# Chunking: la consigna sugiere un punto medio de ~500-800 tokens. Chunks muy
# chicos pierden contexto semántico; muy grandes diluyen el embedding.
CHUNK_SIZE_TOKENS = 600
CHUNK_OVERLAP_TOKENS = 80

# Cantidad de documentos que devuelve el recuperador (y k de las métricas).
TOP_K = 5

REQUIRED_ENV_VARS = ("PINECONE_API_KEY", "OPENAI_API_KEY", "INDEX_NAME")


@dataclass(frozen=True)
class Settings:
    pinecone_api_key: str
    openai_api_key: str
    index_name: str
    # Namespace: separa los datos de este dataset dentro del índice. Sin
    # namespaces, datasets distintos se mezclan y la búsqueda se vuelve
    # ruidosa y más lenta (error común #2).
    namespace: str = "tasklet-docs"
    # El plan gratuito (Starter) de Pinecone solo permite serverless en
    # AWS us-east-1.
    cloud: str = "aws"
    region: str = "us-east-1"
    dimension: int = EMBEDDING_DIMENSION
    embedding_model: str = EMBEDDING_MODEL


def get_settings() -> Settings:
    """Lee y valida las variables de entorno. Falla con un mensaje claro."""
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "Faltan variables de entorno: "
            + ", ".join(missing)
            + ". Copiá .env.example a .env y completalas."
        )
    return Settings(
        pinecone_api_key=os.environ["PINECONE_API_KEY"],
        openai_api_key=os.environ["OPENAI_API_KEY"],
        index_name=os.environ["INDEX_NAME"],
        namespace=os.getenv("PINECONE_NAMESPACE", "tasklet-docs"),
        cloud=os.getenv("PINECONE_CLOUD", "aws"),
        region=os.getenv("PINECONE_REGION", "us-east-1"),
    )
