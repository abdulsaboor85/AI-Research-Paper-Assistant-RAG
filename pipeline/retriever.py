"""Find the most relevant chunks of a paper in ChromaDB."""

import re

from embedder import client, model  # shared model: no second copy loaded

SUMMARY_PATTERNS = (
    "what is this paper about", "what does this paper", "what is the paper about",
    "summarize", "summarise", "summary", "overview", "outline", "brief", "tldr", "tl;dr",
    "what does this document", "what is this document", "tell me about this paper",
    "explain this paper", "what is the main", "what are the main",
    "what is the purpose", "what is the goal",
)

LOW_SIGNAL_PATTERNS = (
    r"\bprovided proper attribution\b", r"\breferences\b", r"\bbibliography\b",
    r"\bconference on\b", r"\bproceedings\b", r"\barxiv\b", r"\bdoi\b",
    r"\bfigure\s+\d+", r"\bfig\.\s*\d+", r"\btable\s+\d+", r"\bwork performed while\b",
)

HIGH_SIGNAL_PATTERNS = (
    r"\babstract\b", r"\bintroduction\b", r"\bconclusion\b", r"\bwe propose\b",
    r"\bwe present\b", r"\bwe introduce\b", r"\bthis paper\b",
    r"\bour contributions\b", r"\bexperiments\b", r"\bresults\b",
)

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def is_summary_question(query: str) -> bool:
    q = query.lower().strip()
    return any(p in q for p in SUMMARY_PATTERNS)


def score_low_signal(chunk: str) -> int:
    """Higher = more like references/boilerplate."""
    text = chunk.lower()
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


def lexical_overlap_score(query: str, chunk: str) -> int:
    q = set(re.findall(r"[a-zA-Z]+", query.lower()))
    c = set(re.findall(r"[a-zA-Z]+", chunk.lower()))
    return len(q & c)


def get_opening_chunks(collection, count: int = 3) -> list[str]:
    try:
        result = collection.get(ids=[f"chunk_{i}" for i in range(count)])
    except Exception:
        return []
    pairs = sorted(zip(result.get("ids", []), result.get("documents", [])),
                   key=lambda p: int(p[0].split("_")[-1]))
    return [doc for _, doc in pairs if doc]


def dedupe_chunks(chunks: list[str]) -> list[str]:
    seen, unique = set(), []
    for chunk in chunks:
        key = re.sub(r"\s+", " ", chunk).strip()[:500]
        if key and key not in seen:
            seen.add(key)
            unique.append(chunk)
    return unique


def retrieve_relevant_chunks(query: str, collection_name: str, top_k: int = 10) -> list[str]:
    collection = client.get_or_create_collection(collection_name)
    summary_mode = is_summary_question(query)

    search_query = query
    if summary_mode:
        search_query += (". abstract introduction objective methodology approach "
                         "contributions experiments results conclusion paper summary")

    embedding = model.encode([QUERY_PREFIX + search_query]).tolist()
    results = collection.query(
        query_embeddings=embedding,
        n_results=max(top_k * 5, 30 if summary_mode else 20),
    )

    ranked = []
    for rank, (chunk, distance) in enumerate(zip(results["documents"][0], results["distances"][0])):
        score = distance - lexical_overlap_score(query, chunk) * 0.1
        if summary_mode:
            score += score_low_signal(chunk) * 0.35 - score_high_signal(chunk) * 0.2
        ranked.append((score, rank, chunk))
    ranked.sort(key=lambda item: (item[0], item[1]))

    selected = [c for _, _, c in ranked if not summary_mode or score_low_signal(c) < 2]
    if summary_mode:
        selected = get_opening_chunks(collection) + selected

    return dedupe_chunks(selected)[:max(top_k, 10)]