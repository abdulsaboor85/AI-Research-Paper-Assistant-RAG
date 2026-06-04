"""Retrieve relevant text chunks from ChromaDB."""

import re
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL_NAME    = "BAAI/bge-base-en-v1.5"
DEFAULT_COLLECTION_NAME = "research_papers_v2"
BASE_DIR    = Path(__file__).resolve().parent.parent
CHROMA_PATH = BASE_DIR / "chroma_db"

SUMMARY_QUESTION_PATTERNS = (
    "what is this paper about",
    "what does this paper",
    "what is the paper about",
    "summarize", "summarise", "summary",
    "overview", "outline", "brief", "tldr", "tl;dr",
    "what does this document",
    "what is this document",
    "tell me about this paper",
    "explain this paper",
    "what is the main",
    "what are the main",
    "what is the purpose",
    "what is the goal",
)

LOW_SIGNAL_PATTERNS = (
    r"\bprovided proper attribution\b",
    r"\breferences\b",
    r"\bbibliography\b",
    r"\bconference on\b",
    r"\bproceedings\b",
    r"\barxiv\b",
    r"\bdoi\b",
    r"\bfigure\s+\d+",
    r"\bfig\.\s*\d+",
    r"\btable\s+\d+",
    r"\bwork performed while\b",
)

HIGH_SIGNAL_PATTERNS = (
    r"\babstract\b",
    r"\bintroduction\b",
    r"\bconclusion\b",
    r"\bwe propose\b",
    r"\bwe present\b",
    r"\bwe introduce\b",
    r"\bthis paper\b",
    r"\bour contributions\b",
    r"\bexperiments\b",
    r"\bresults\b",
)

# ── Shared singletons — one model + one client per Flask worker process ──────
# Importing this module multiple times does NOT reload the model; Python caches
# the module object so these lines run exactly once per process.
model  = SentenceTransformer(EMBEDDING_MODEL_NAME)
client = chromadb.PersistentClient(path=str(CHROMA_PATH))


def is_summary_question(query: str) -> bool:
    normalized = query.lower().strip()
    return any(pattern in normalized for pattern in SUMMARY_QUESTION_PATTERNS)


def score_low_signal(chunk: str) -> int:
    text  = chunk.lower()
    score = sum(1 for p in LOW_SIGNAL_PATTERNS if re.search(p, text))

    year_count = len(re.findall(r"\b(?:19|20)\d{2}\b", text))
    if year_count >= 5:
        score += 2

    digit_ratio = sum(c.isdigit() for c in text) / max(len(text), 1)
    if digit_ratio > 0.12:
        score += 2

    words = re.findall(r"[a-zA-Z]+", text)
    if words and len(set(words)) / len(words) < 0.35:
        score += 1

    return score


def score_high_signal(chunk: str) -> int:
    text = chunk.lower()
    return sum(1 for p in HIGH_SIGNAL_PATTERNS if re.search(p, text))


def get_opening_chunks(collection, count: int = 3) -> list[str]:
    chunk_ids = [f"chunk_{i}" for i in range(count)]
    try:
        result = collection.get(ids=chunk_ids)
    except Exception:
        return []
    pairs   = zip(result.get("ids", []), result.get("documents", []))
    ordered = sorted(pairs, key=lambda p: int(p[0].split("_")[-1]) if "_" in p[0] else 0)
    return [doc for _, doc in ordered if doc]


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
            f"{query}. abstract introduction objective methodology approach "
            "contributions experiments results conclusion paper summary"
        )

    query_embedding = model.encode(
        [f"Represent this sentence for searching relevant passages: {search_query}"]
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

    selected = dedupe_chunks(selected)
    return selected[:max(top_k, 10)]