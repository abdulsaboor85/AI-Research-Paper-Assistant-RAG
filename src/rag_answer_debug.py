"""
Run a PDF question through RAG and print the evidence directly.

Example:
    python src/rag_answer_debug.py "papers/easy/cybersecurity_easy.pdf" "what should employees do"

Optional:
    python src/rag_answer_debug.py "papers/easy/cybersecurity_easy.pdf" "what should employees do" --full-vectors
"""

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
    left_norm = np.linalg.norm(left)
    right_norm = np.linalg.norm(right)
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return float(np.dot(left, right) / (left_norm * right_norm))


def format_vector(vector: Iterable[float], preview_dims: int, full_vectors: bool) -> str:
    values = list(vector if full_vectors else list(vector)[:preview_dims])
    formatted = ", ".join(f"{value:.6f}" for value in values)
    suffix = "" if full_vectors else ", ..."
    return f"[{formatted}{suffix}]"


def print_section(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def run(pdf_path: str, question: str, top_k: int, preview_dims: int, full_vectors: bool) -> None:
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if not pdf_path.lower().endswith(".pdf"):
        raise ValueError("Input file must be a PDF.")
    if not os.getenv("GEMINI_API_KEY"):
        raise ValueError("GEMINI_API_KEY is missing from .env.")

    print_section("RAG Answer Debug")
    print(f"PDF: {os.path.relpath(pdf_path, PROJECT_ROOT)}")
    print(f"Embedding model: BAAI/bge-base-en-v1.5")
    print(f"Top K selected chunks: {top_k}")

    print_section("Extracting And Chunking")
    raw_text = extract_text(pdf_path)
    chunks = chunk_text(raw_text)
    print(f"Extracted words: {len(raw_text.split())}")
    print(f"Total chunks: {len(chunks)}")

    print_section("Embedding")
    chunk_vectors = embedding_model.encode(chunks)
    question_vector = embedding_model.encode([EMBED_QUERY_PREFIX + question])[0]
    vector_dims = len(question_vector)
    print(f"Vector dimensions: {vector_dims}")

    scored_chunks = []
    for index, (chunk, chunk_vector) in enumerate(zip(chunks, chunk_vectors), start=1):
        score = cosine_similarity(question_vector, chunk_vector)
        scored_chunks.append(
            {
                "index": index,
                "text": chunk,
                "vector": chunk_vector,
                "score": score,
            }
        )

    ranked_chunks = sorted(scored_chunks, key=lambda item: item["score"], reverse=True)
    selected_chunks = ranked_chunks[:top_k]

    print_section("Question")
    print(question)
    print("\nQuestion vector:")
    print(format_vector(question_vector, preview_dims, full_vectors))

    print_section("All Chunks With Vectors")
    for chunk in scored_chunks:
        print(f"\nChunk {chunk['index']}:")
        print(chunk["text"])
        print("Vector:")
        print(format_vector(chunk["vector"], preview_dims, full_vectors))
        print(f"Similarity with question: {chunk['score']:.6f}")

    print_section("Selected Chunks")
    for rank, chunk in enumerate(selected_chunks, start=1):
        print(f"\nRank {rank} | Chunk {chunk['index']} | Similarity: {chunk['score']:.6f}")
        print(chunk["text"])
        print("Vector:")
        print(format_vector(chunk["vector"], preview_dims, full_vectors))

    print_section("Answer")
    answer = answer_question(question, [chunk["text"] for chunk in selected_chunks])
    print(answer)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print RAG chunks, vectors, selected chunks, question vector, and final answer."
    )
    parser.add_argument("pdf_path", help="Path to the PDF paper.")
    parser.add_argument("question", help="Question to ask about the paper.")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="Number of chunks to use for the answer.")
    parser.add_argument(
        "--preview-dims",
        type=int,
        default=DEFAULT_VECTOR_PREVIEW_DIMS,
        help="Number of vector dimensions to print when --full-vectors is not used.",
    )
    parser.add_argument("--full-vectors", action="store_true", help="Print every vector dimension.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args.pdf_path, args.question, args.top_k, args.preview_dims, args.full_vectors)
