from sentence_transformers import SentenceTransformer
import chromadb
import os
import re

model = SentenceTransformer("BAAI/bge-base-en-v1.5")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
client = chromadb.PersistentClient(path=os.path.join(BASE_DIR, "chroma_db"))

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


def _is_summary_question(query):
    normalized = query.lower().strip()
    return any(pattern in normalized for pattern in SUMMARY_QUESTION_PATTERNS)


def _low_signal_score(chunk):
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


def _high_signal_score(chunk):
    text = chunk.lower()
    return sum(1 for pattern in HIGH_SIGNAL_PATTERNS if re.search(pattern, text))


def _get_opening_chunks(collection, count=3):
    ids = [f"chunk_{i}" for i in range(count)]
    try:
        result = collection.get(ids=ids)
    except Exception:
        return []

    pairs = zip(result.get("ids", []), result.get("documents", []))
    ordered = sorted(
        pairs,
        key=lambda pair: int(pair[0].split("_")[-1]) if "_" in pair[0] else 0,
    )
    return [document for _, document in ordered if document]


def _dedupe(chunks):
    seen = set()
    unique_chunks = []
    for chunk in chunks:
        key = re.sub(r"\s+", " ", chunk).strip()[:500]
        if key and key not in seen:
            seen.add(key)
            unique_chunks.append(chunk)
    return unique_chunks


def retrieve_relevant_chunks(query, collection_name="research_papers_v2", top_k=10):
    collection = client.get_or_create_collection(collection_name)

    is_summary = _is_summary_question(query)
    search_query = query
    if is_summary:
        search_query = (
            f"{query}. abstract introduction objective methodology approach "
            "contributions experiments results conclusion paper summary"
        )

    query_embedding = model.encode(
        [f"Represent this sentence for searching relevant passages: {search_query}"]
    ).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=max(top_k * 3, 20 if is_summary else top_k),
    )

    chunks = results["documents"][0]
    scores = results["distances"][0]

    candidates = []
    for rank, (chunk, score) in enumerate(zip(chunks, scores)):
        adjusted_score = score
        if is_summary:
            adjusted_score += _low_signal_score(chunk) * 0.35
            adjusted_score -= _high_signal_score(chunk) * 0.2
        candidates.append((adjusted_score, rank, chunk))

    candidates.sort(key=lambda item: (item[0], item[1]))
    selected = [
        chunk
        for _, _, chunk in candidates
        if not is_summary or _low_signal_score(chunk) < 2
    ]

    if is_summary:
        selected = _get_opening_chunks(collection) + selected

    selected = _dedupe(selected)
    return selected[:max(top_k, 7)]
