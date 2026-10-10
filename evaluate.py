"""Evaluación del recuperador con un "golden set": Precision@k y Recall@k.

El golden set (`golden_set.json`) es una lista de pares
    {"pregunta": "...", "documento_id_esperado": "<doc_id>"}
donde sabemos de antemano qué documento contiene la respuesta. Para cada
pregunta ejecutamos el recuperador, miramos el `doc_id` de los top-k chunks
y calculamos:

- **Recall@k**: ¿apareció el documento correcto entre los k recuperados?
  (fracción de documentos esperados que aparecen; con un solo documento
  esperado por pregunta vale 1 o 0).
- **Precision@k**: de los k chunks recuperados, ¿qué fracción pertenece al
  documento esperado? Se mide a nivel de chunk.

Ojo con interpretar Precision@k: si el documento esperado se partió en pocos
chunks (por ejemplo 2), aunque el recuperador sea perfecto no puede traer más
de 2 chunks "útiles" entre los 5, y la precisión máxima posible es 2/5 = 0.40.
Por eso el reporte muestra también ese máximo posible junto a cada valor.

Uso:
    python evaluate.py              # evalúa el recuperador híbrido
    python evaluate.py --compare    # compara híbrido vs. solo vector vs. solo BM25
"""

import argparse
import json
import logging
from pathlib import Path

from config import GOLDEN_SET_PATH, TOP_K, get_settings
from rag_system import MODES, RAGSystem

logger = logging.getLogger("evaluate")


# --------------------------------------------------------------------------
# Métricas (funciones puras, fáciles de testear)
# --------------------------------------------------------------------------
def load_golden_set(path: Path = GOLDEN_SET_PATH) -> list[dict]:
    datos = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(datos, list) or not datos:
        raise ValueError(f"{path} tiene que ser una lista no vacía de preguntas.")
    for i, item in enumerate(datos, start=1):
        if "pregunta" not in item or "documento_id_esperado" not in item:
            raise ValueError(
                f"El ítem {i} de {path} necesita las claves 'pregunta' y "
                "'documento_id_esperado'."
            )
    return datos


def expected_set(valor) -> set[str]:
    """`documento_id_esperado` puede ser un id o una lista de ids."""
    return {valor} if isinstance(valor, str) else set(valor)


def validate_golden_ids(golden: list[dict], known_doc_ids: set[str]) -> None:
    """Un id mal escrito en el golden set daría Recall 0 sin ningún aviso:
    mejor fallar antes de evaluar."""
    for item in golden:
        desconocidos = expected_set(item["documento_id_esperado"]) - known_doc_ids
        if desconocidos:
            raise ValueError(
                f"El golden set espera documentos que no existen en el índice: "
                f"{sorted(desconocidos)}. Documentos disponibles: "
                f"{sorted(known_doc_ids)}."
            )


def compute_metrics(retrieved_doc_ids: list[str], expected: set[str], k: int) -> dict:
    """Precision@k y Recall@k para una pregunta."""
    top = retrieved_doc_ids[:k]
    aciertos = sum(1 for doc_id in top if doc_id in expected)
    encontrados = {doc_id for doc_id in top if doc_id in expected}
    # Posición (desde 1) del primer chunk relevante; 0 si no apareció ninguno.
    primera_posicion = next(
        (i for i, doc_id in enumerate(top, start=1) if doc_id in expected), 0
    )
    return {
        "recall": len(encontrados) / len(expected),
        "precision": aciertos / k,
        "aciertos": aciertos,
        "primera_posicion": primera_posicion,
        "reciprocal_rank": 1 / primera_posicion if primera_posicion else 0.0,
    }


def max_precision(expected: set[str], chunks_per_doc: dict[str, int], k: int) -> float:
    """Mejor Precision@k posible: no se pueden recuperar más chunks útiles que
    los que existen de los documentos esperados."""
    disponibles = sum(chunks_per_doc.get(doc_id, 0) for doc_id in expected)
    return min(k, disponibles) / k


def evaluate_retriever(
    rag, golden: list[dict], *, mode: str = "hybrid", k: int = TOP_K
) -> list[dict]:
    """Corre todas las preguntas del golden set y devuelve un resultado por pregunta."""
    resultados = []
    chunks_per_doc = rag.chunks_per_doc
    for item in golden:
        esperado = expected_set(item["documento_id_esperado"])
        docs = rag.retrieve(item["pregunta"], mode=mode)
        recuperados = [d.metadata.get("doc_id") for d in docs]
        metricas = compute_metrics(recuperados, esperado, k)
        resultados.append(
            {
                "pregunta": item["pregunta"],
                "esperado": sorted(esperado),
                "recuperados": recuperados[:k],
                "max_precision": max_precision(esperado, chunks_per_doc, k),
                **metricas,
            }
        )
    return resultados


def summarize(resultados: list[dict]) -> dict:
    n = len(resultados)
    return {
        "recall": sum(r["recall"] for r in resultados) / n,
        "precision": sum(r["precision"] for r in resultados) / n,
        "mrr": sum(r["reciprocal_rank"] for r in resultados) / n,
        "max_precision": sum(r["max_precision"] for r in resultados) / n,
        "preguntas_con_acierto": sum(1 for r in resultados if r["recall"] > 0),
        "total": n,
    }


# --------------------------------------------------------------------------
# Reporte en consola
# --------------------------------------------------------------------------
def print_detail(resultados: list[dict], mode: str, k: int) -> None:
    print(f"\n=== Detalle por pregunta — modo '{mode}' (k={k}) ===")
    for i, r in enumerate(resultados, start=1):
        marca = "OK " if r["recall"] > 0 else "FALLO"
        print(f"\n[{marca}] Pregunta {i}: {r['pregunta']}")
        print(f"   Esperado : {', '.join(r['esperado'])}")
        print(f"   Top-{k}    : {', '.join(str(d) for d in r['recuperados'])}")
        posicion = (
            f"puesto #{r['primera_posicion']}" if r["primera_posicion"] else "no apareció"
        )
        print(
            f"   Recall@{k} = {r['recall']:.2f}   "
            f"Precision@{k} = {r['precision']:.2f} (máx. posible {r['max_precision']:.2f})   "
            f"Primer acierto: {posicion}"
        )


def print_summary(por_modo: dict[str, list[dict]], k: int) -> None:
    print(f"\n=== Resumen (k={k}) ===")
    print(
        f"{'Modo':<10} {'Recall@' + str(k):>10} {'Precision@' + str(k):>14} "
        f"{'Máx. posible':>14} {'MRR':>7} {'Aciertos':>10}"
    )
    for modo, resultados in por_modo.items():
        s = summarize(resultados)
        print(
            f"{modo:<10} {s['recall']:>10.2f} {s['precision']:>14.2f} "
            f"{s['max_precision']:>14.2f} {s['mrr']:>7.2f} "
            f"{s['preguntas_con_acierto']:>7}/{s['total']}"
        )
    print(
        "\nNotas:\n"
        "- Precision@k se mide por chunk y está acotada por la cantidad de chunks "
        "que tiene el documento esperado (columna 'Máx. posible').\n"
        "- MRR (extra) promedia 1/posición del primer acierto: 1.00 significa que "
        "el documento correcto salió siempre primero. Distingue modos cuando el "
        "Recall ya llegó a 1.00 en todos."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evalúa el recuperador (Precision@k / Recall@k).")
    parser.add_argument("--golden", default=str(GOLDEN_SET_PATH), help="Ruta al golden set JSON.")
    parser.add_argument("--k", type=int, default=TOP_K, help="Cantidad de chunks a recuperar.")
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compara híbrido, solo vectorial y solo BM25.",
    )
    args = parser.parse_args()

    try:
        golden = load_golden_set(Path(args.golden))
        rag = RAGSystem(get_settings(), k=args.k)
        validate_golden_ids(golden, set(rag.chunks_per_doc))
    except (RuntimeError, ValueError) as error:
        raise SystemExit(f"Error: {error}")

    modos = MODES if args.compare else ("hybrid",)
    por_modo = {
        modo: evaluate_retriever(rag, golden, mode=modo, k=args.k) for modo in modos
    }

    print_detail(por_modo["hybrid"], "hybrid", args.k)
    print_summary(por_modo, args.k)


if __name__ == "__main__":
    main()
