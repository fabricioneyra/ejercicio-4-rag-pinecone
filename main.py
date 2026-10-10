"""Demo del recuperador híbrido: muestra los top-5 chunks de una consulta.

Uso:
    python main.py "¿Qué significa el error E4021?"
    python main.py "cómo reintentar una tarea" --category referencia
    python main.py "error E4021" --mode vector     # solo búsqueda vectorial
    python main.py                                  # corre dos consultas de ejemplo
"""

import argparse

from rag_system import MODES, RAGSystem

CONSULTAS_DE_EJEMPLO = [
    # Término exacto (código de error): donde BM25 aporta más.
    "¿Qué significa el error E4021?",
    # Pregunta semántica, sin las palabras exactas de la documentación.
    "¿Cómo evito que un worker pierda trabajo cuando lo apago?",
]


def mostrar(consulta: str, docs: list) -> None:
    print(f"\n{'=' * 70}\nConsulta: {consulta}\n{'=' * 70}")
    for posicion, doc in enumerate(docs, start=1):
        meta = doc.metadata
        # Pinecone devuelve los números como float (1.0): lo mostramos como entero.
        pagina = int(meta["page"]) if meta.get("page") is not None else "?"
        fragmento = " ".join(doc.page_content.split())[:160]
        print(
            f"\n#{posicion}  {meta.get('doc_id')}  ({meta.get('chunk_id')})"
            f"\n    categoría: {meta.get('category')} | página: {pagina} | "
            f"tags: {', '.join(meta.get('tags', []))}"
            f"\n    fuente: {meta.get('source')}"
            f"\n    «{fragmento}...»"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Consulta el recuperador híbrido.")
    parser.add_argument("consulta", nargs="*", help="Texto de la consulta.")
    parser.add_argument("--mode", choices=MODES, default="hybrid")
    parser.add_argument("--category", help="Filtrar por categoría de metadata.")
    args = parser.parse_args()

    consultas = [" ".join(args.consulta)] if args.consulta else CONSULTAS_DE_EJEMPLO
    try:
        rag = RAGSystem()
        for consulta in consultas:
            docs = rag.retrieve(consulta, mode=args.mode, category=args.category)
            mostrar(consulta, docs)
    except (RuntimeError, ValueError) as error:
        raise SystemExit(f"Error: {error}")


if __name__ == "__main__":
    main()
