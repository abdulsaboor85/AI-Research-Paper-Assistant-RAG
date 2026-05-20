"""Print RAG chunks, vectors, selected chunks, and the final answer."""

import argparse
import os
import sys
from typing import Iterable

import numpy as np
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE_DIR = os.path.join(PROJECT_ROOT, "pipeline")
sys.path.insert(0, PIPELINE_DIR)

from chunker import chunk_text
from embedder import model as embedding_model
from extractor import extract_text
from qa_engine import answer_question

EMBED_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
DEFAULT_TOP_K = 3
DEFAULT_VECTOR_PREVIEW_DIMS = 12


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    norm = np.linalg.norm(left) * np.linalg.norm(right)
    return 0.0 if norm == 0 else float(np.dot(left, right) / norm)


def format_vector(vector: Iterable[float], preview_dims: int, full_vectors: bool) -> str:
    values = list(vector if full_vectors else vector[:preview_dims])
    suffix = "" if full_vectors else ", ..."
    return f"[{', '.join(f'{value:.6f}' for value in values)}{suffix}]"


def print_section(title: str) -> None:
    print(f"\n{'=' * 80}\n{title}\n{'=' * 80}")


def load_pdf_state(pdf_path: str) -> tuple[str, list[str]]:
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    if not os.path.exists(pdf_path) or not pdf_path.lower().endswith(".pdf"):
        raise ValueError(f"Invalid PDF path: {pdf_path}")
    if not os.getenv("GEMINI_API_KEY"):
        raise ValueError("GEMINI_API_KEY is missing from .env.")
    raw_text = extract_text(pdf_path)
    return raw_text, chunk_text(raw_text)


def score_chunks(question: str, chunks: list[str]):
    question_vector = embedding_model.encode([EMBED_QUERY_PREFIX + question])[0]
    chunk_vectors = embedding_model.encode(chunks)
    scored = [
        {
            "index": index,
            "text": chunk,
            "vector": vector,
            "score": cosine_similarity(question_vector, vector),
        }
        for index, (chunk, vector) in enumerate(zip(chunks, chunk_vectors), start=1)
    ]
    return question_vector, sorted(scored, key=lambda item: item["score"], reverse=True)


def print_chunks(title: str, chunks, preview_dims: int, full_vectors: bool) -> None:
    print_section(title)
    for chunk in chunks:
        print(f"\nChunk {chunk['index']} | Similarity: {chunk['score']:.6f}")
        print(chunk["text"])
        print("Vector:")
        print(format_vector(chunk["vector"], preview_dims, full_vectors))


def run(pdf_path: str, question: str, top_k: int, preview_dims: int, full_vectors: bool) -> None:
    raw_text, chunks = load_pdf_state(pdf_path)

    print_section("RAG Answer Debug")
    print(f"PDF: {os.path.relpath(pdf_path, PROJECT_ROOT)}")
    print("Embedding model: BAAI/bge-base-en-v1.5")
    print(f"Top K selected chunks: {top_k}")

    print_section("Extracting And Chunking")
    print(f"Extracted words: {len(raw_text.split())}")
    print(f"Total chunks: {len(chunks)}")

    print_section("Embedding")
    question_vector, scored_chunks = score_chunks(question, chunks)
    selected_chunks = scored_chunks[:top_k]
    print(f"Vector dimensions: {len(question_vector)}")

    print_section("Question")
    print(question)
    print("\nQuestion vector:")
    print(format_vector(question_vector, preview_dims, full_vectors))

    print_chunks("All Chunks With Vectors", scored_chunks, preview_dims, full_vectors)
    print_chunks("Selected Chunks", selected_chunks, preview_dims, full_vectors)

    print_section("Answer")
    print(answer_question(question, [chunk["text"] for chunk in selected_chunks]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print RAG chunks, vectors, and the final answer.")
    parser.add_argument("pdf_path", help="Path to the PDF paper.")
    parser.add_argument("question", help="Question to ask about the paper.")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--preview-dims", type=int, default=DEFAULT_VECTOR_PREVIEW_DIMS)
    parser.add_argument("--full-vectors", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args.pdf_path, args.question, args.top_k, args.preview_dims, args.full_vectors)
