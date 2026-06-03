
import re
from pathlib import Path

import chromadb

EMBEDDING_MODEL_NAME    = "BAAI/bge-base-en-v1.5"
DEFAULT_COLLECTION_NAME = "research_papers_v2"
BASE_DIR    = Path(__file__).resolve().parent.parent
CHROMA_PATH = BASE_DIR / "chroma_db"

# Re-use singletons from embedder - zero extra loading cost
from embedder import model, client

SUMMARY_QUESTION_PATTERNS = (
    ""
)

LOW_SIGNAL_PATTERNS = (
    r"\bprovided proper attribution\b",
    r"\breferences\b", r"\bbibliography\b",
    r"\bconference on\b", r"\bproceedings\b",
    r"\barxiv\b", r"\bdoi\b",
    r"\bfigure\s+\d+", r"\bfig\.\s*\d+",
    r"\btable\s+\d+", r"\bwork performed while\b",
)

HIGH_SIGNAL_PATTERNS = (
    r"\babstract\b", r"\bintroduction\b", r"\bconclusion\b",
    r"\bwe propose\b", r"\bwe present\b", r"\bwe introduce\b",
    r"\bthis paper\b", r"\bour contributions\b",
    r"\bexperiments\b", r"\bresults\b",
)


def is_summary_question(query: str) -> bool:
    n = query.lower().strip()
    return any(p in n for p in SUMMARY_QUESTION_PATTERNS)


def score_low_signal(chunk: str) -> int:
    text  = chunk.lower()
    score = sum(1 for p in LOW_SIGNAL_PATTERNS if re.search(p, text))
    if len(re.findall(r"\b(?:19|20)\d{2}\b", text)) >= 5:
        score += 2
    if sum(c.isdigit() for c in text) / max(len(text), 1) > 0.12:
        score += 2
    words = re.findall(r"[a-zA-Z]+", text)
    if words and len(set(words)) / len(words) < 0.35:
        score += 1
    return score


def score_high_signal(chunk: str) -> int:
    text = chunk.lower()
    return sum(1 for p in HIGH_SIGNAL_PATTERNS if re.search(p, text))


def get_opening_chunks(collection, count: int = 3) -> list[str]:
    try:
        result  = collection.get(ids=[f"chunk_{i}" for i in range(count)])
        pairs   = zip(result.get("ids", []), result.get("documents", []))
        ordered = sorted(pairs, key=lambda p: int(p[0].split("_")[-1]) if "_" in p[0] else 0)
        return [doc for _, doc in ordered if doc]
    except Exception:
        return []


def dedupe_chunks(chunks: list[str]) -> list[str]:
    seen, out = set(), []
    for chunk in chunks:
        key = re.sub(r"\s+", " ", chunk).strip()[:500]
        if key and key not in seen:
            seen.add(key)
            out.append(chunk)
    return out


def lexical_overlap_score(query: str, chunk: str) -> int:
    qw = set(re.findall(r"[a-zA-Z]+", query.lower()))
    cw = set(re.findall(r"[a-zA-Z]+", chunk.lower()))
    return len(qw & cw)


def retrieve_relevant_chunks(
    query: str,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    top_k: int = 10,
) -> list[str]:
    collection   = client.get_or_create_collection(collection_name)
    summary_mode = is_summary_question(query)

    search_query = query
    if summary_mode:
        search_query = (
            f"{query}. abstract introduction objective methodology "
            "contributions experiments results conclusion paper summary"
        )

    query_embedding = model.encode(
        [f"Represent this sentence for searching relevant passages: {search_query}"],
        convert_to_numpy=True,
    ).tolist()

    candidate_limit = max(top_k * 5, 30 if summary_mode else 20)
    results   = collection.query(query_embeddings=query_embedding, n_results=candidate_limit)
    chunks    = results["documents"][0]
    distances = results["distances"][0]

    ranked = []
    for rank, (chunk, dist) in enumerate(zip(chunks, distances)):
        adj = dist - (lexical_overlap_score(query, chunk) * 0.1)
        if summary_mode:
            adj += score_low_signal(chunk)  * 0.35
            adj -= score_high_signal(chunk) * 0.2
        ranked.append((adj, rank, chunk))

    ranked.sort(key=lambda x: (x[0], x[1]))
    selected = [c for _, _, c in ranked if not summary_mode or score_low_signal(c) < 2]

    if summary_mode:
        selected = get_opening_chunks(collection) + selected

    return dedupe_chunks(selected)[:max(top_k, 10)]