"""Retrieve relevant text chunks from ChromaDB."""

import re
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL_NAME = "BAAI/bge-base-en-v1.5"
DEFAULT_COLLECTION_NAME = "research_papers_v2"
BASE_DIR = Path(__file__).resolve().parent.parent
CHROMA_PATH = BASE_DIR / "chroma_db"

SUMMARY_QUESTION_PATTERNS = (
    "what is this paper about",
    "what is the paper about",
    "summarize",
    "summary",
    "main idea",
    "overall topic",
    "objective",
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

model = SentenceTransformer(EMBEDDING_MODEL_NAME)
client = chromadb.PersistentClient(path=str(CHROMA_PATH))


def is_summary_question(query: str) -> bool:
    normalized_query = query.lower().strip()
    return any(pattern in normalized_query for pattern in SUMMARY_QUESTION_PATTERNS)


def score_low_signal(chunk: str) -> int:
    text = chunk.lower()
    score = sum(1 for pattern in LOW_SIGNAL_PATTERNS if re.search(pattern, text))

    year_count = len(re.findall(r"\b(?:19|20)\d{2}\b", text))
    if year_count >= 5:
        score += 2

    digit_ratio = sum(character.isdigit() for character in text) / max(len(text), 1)
    if digit_ratio > 0.12:
        score += 2

    words = re.findall(r"[a-zA-Z]+", text)
    if words and len(set(words)) / len(words) < 0.35:
        score += 1

    return score


def score_high_signal(chunk: str) -> int:
    text = chunk.lower()
    return sum(1 for pattern in HIGH_SIGNAL_PATTERNS if re.search(pattern, text))


def get_opening_chunks(collection, count: int = 3) -> list[str]:
    chunk_ids = [f"chunk_{index}" for index in range(count)]

    try:
        result = collection.get(ids=chunk_ids)
    except Exception:
        return []

    pairs = zip(result.get("ids", []), result.get("documents", []))
    ordered = sorted(
        pairs,
        key=lambda pair: int(pair[0].split("_")[-1]) if "_" in pair[0] else 0,
    )
    return [document for _, document in ordered if document]


def dedupe_chunks(chunks: list[str]) -> list[str]:
    seen = set()
    unique_chunks = []

    for chunk in chunks:
        key = re.sub(r"\s+", " ", chunk).strip()[:500]
        if key and key not in seen:
            seen.add(key)
            unique_chunks.append(chunk)

    return unique_chunks


def lexical_overlap_score(query: str, chunk: str) -> int:
    query_words = set(re.findall(r"[a-zA-Z]+", query.lower()))
    chunk_words = set(re.findall(r"[a-zA-Z]+", chunk.lower()))
    return len(query_words & chunk_words)


def retrieve_relevant_chunks(
    query: str,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    top_k: int = 10,
) -> list[str]:
    collection = client.get_or_create_collection(collection_name)
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
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=candidate_limit,
    )

    chunks = results["documents"][0]
    distances = results["distances"][0]

    ranked_candidates = []
    for rank, (chunk, distance) in enumerate(zip(chunks, distances)):
        adjusted_distance = distance - (lexical_overlap_score(query, chunk) * 0.1)

        if summary_mode:
            adjusted_distance += score_low_signal(chunk) * 0.35
            adjusted_distance -= score_high_signal(chunk) * 0.2

        ranked_candidates.append((adjusted_distance, rank, chunk))

    ranked_candidates.sort(key=lambda item: (item[0], item[1]))

    selected_chunks = [
        chunk
        for _, _, chunk in ranked_candidates
        if not summary_mode or score_low_signal(chunk) < 2
    ]

    if summary_mode:
        selected_chunks = get_opening_chunks(collection) + selected_chunks

    selected_chunks = dedupe_chunks(selected_chunks)
    return selected_chunks[:max(top_k, 10)]
