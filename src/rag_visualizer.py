"""
Backward-compatible entrypoint for the terminal RAG answer debug flow.

Prefer:
    python src/rag_answer_debug.py "papers/your_paper.pdf" "your question"
"""

from rag_answer_debug import parse_args, run


if __name__ == "__main__":
    args = parse_args()
    run(args.pdf_path, args.question, args.top_k, args.preview_dims, args.full_vectors)
