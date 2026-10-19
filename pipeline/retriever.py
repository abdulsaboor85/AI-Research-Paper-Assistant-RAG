"""
retriever.py  -  find the pieces of a paper that best answer a question.

HOW THIS FILE WORKS (easy words)
------------------------------------------------------------
1. Turn the question into numbers, then ask ChromaDB for the closest chunks.
2. Improve the order: chunks that share words with the question move up.
3. If the question is general ("what is this paper about?"), we also:
     - push down chunks that look like reference lists or tables,
     - push up chunks with words like "abstract", "we propose", "conclusion",
     - always add the first 3 chunks of the paper (title + abstract).
4. Remove repeated chunks and return the best ones.

FUNCTION GUIDE
------------------------------------------------------------
   is_summary_question     is it a general question like "summarize this paper"?
   score_low_signal        how much a chunk looks like references (higher = worse)
   score_high_signal       how much a chunk looks important
   get_opening_chunks      the first chunks of the paper
   chunk_number            "chunk_12" -> 12 (used for sorting)
   dedupe_chunks           remove repeated chunks
   lexical_overlap_score   how many words the question and a chunk share
   first_item              helper for sorting
   retrieve_relevant_chunks   the main function: the best chunks for a question
"""

import re

from embedder import DEFAULT_COLLECTION_NAME, client, model

# Questions that ask for a general overview
SUMMARY_QUESTION_WORDS = [
    "what is this paper about", "what does this paper", "what is the paper about",
    "summarize", "summarise", "summary", "overview", "outline", "brief", "tldr", "tl;dr",
    "what does this document", "what is this document", "tell me about this paper",
    "explain this paper", "what is the main", "what are the main",
    "what is the purpose", "what is the goal",
]

# Chunks with these patterns are usually references or boilerplate
LOW_SIGNAL_PATTERNS = [
    r"\bprovided proper attribution\b", r"\breferences\b", r"\bbibliography\b",
    r"\bconference on\b", r"\bproceedings\b", r"\barxiv\b", r"\bdoi\b",
    r"\bfigure\s+\d+", r"\bfig\.\s*\d+", r"\btable\s+\d+", r"\bwork performed while\b",
]

# Chunks with these patterns are usually important
HIGH_SIGNAL_PATTERNS = [
    r"\babstract\b", r"\bintroduction\b", r"\bconclusion\b", r"\bwe propose\b",
    r"\bwe present\b", r"\bwe introduce\b", r"\bthis paper\b", r"\bour contributions\b",
    r"\bexperiments\b", r"\bresults\b",
]


def is_summary_question(question):
    text = question.lower().strip()
    for words in SUMMARY_QUESTION_WORDS:
        if words in text:
            return True
    return False


def score_low_signal(chunk):
    """Higher = the chunk looks more like references or boilerplate."""
    text = chunk.lower()
    score = 0
    for pattern in LOW_SIGNAL_PATTERNS:
        if re.search(pattern, text):
            score += 1

    # many years (1999, 2015...) -> probably a reference list
    if len(re.findall(r"\b(?:19|20)\d{2}\b", text)) >= 5:
        score += 2

    # mostly digits -> probably a table
    digits = 0
    for letter in text:
        if letter.isdigit():
            digits += 1
    if digits / max(len(text), 1) > 0.12:
        score += 2

    # very few different words -> repeated text
    words = re.findall(r"[a-zA-Z]+", text)
    if words and len(set(words)) / len(words) < 0.35:
        score += 1
    return score


def score_high_signal(chunk):
    text = chunk.lower()
    score = 0
    for pattern in HIGH_SIGNAL_PATTERNS:
        if re.search(pattern, text):
            score += 1
    return score


def chunk_number(pair):
    """("chunk_12", "text") -> 12"""
    return int(pair[0].split("_")[-1])


def get_opening_chunks(collection, count=3):
    """The first few chunks of the paper, in order."""
    ids = []
    for i in range(count):
        ids.append("chunk_" + str(i))
    try:
        result = collection.get(ids=ids)
    except Exception:
        return []

    pairs = list(zip(result.get("ids", []), result.get("documents", [])))
    pairs.sort(key=chunk_number)

    chunks = []
    for chunk_id, document in pairs:
        if document:
            chunks.append(document)
    return chunks


def dedupe_chunks(chunks):
    seen = set()
    unique = []
    for chunk in chunks:
        key = re.sub(r"\s+", " ", chunk).strip()[:500]
        if key and key not in seen:
            seen.add(key)
            unique.append(chunk)
    return unique


def lexical_overlap_score(question, chunk):
    """How many different words the question and the chunk share."""
    question_words = set(re.findall(r"[a-zA-Z]+", question.lower()))
    chunk_words = set(re.findall(r"[a-zA-Z]+", chunk.lower()))
    return len(question_words & chunk_words)


def first_item(row):
    return row[0]


def retrieve_relevant_chunks(question, collection_name=DEFAULT_COLLECTION_NAME, top_k=10):
    """Return the best chunks (a list of texts) for the question."""
    collection = client.get_or_create_collection(collection_name)
    summary_mode = is_summary_question(question)

    search_text = question
    if summary_mode:
        search_text = (question + ". abstract introduction objective methodology approach "
                       "contributions experiments results conclusion paper summary")

    prefix = "Represent this sentence for searching relevant passages: "
    question_numbers = model.encode([prefix + search_text]).tolist()

    if summary_mode:
        candidate_limit = max(top_k * 5, 30)
    else:
        candidate_limit = max(top_k * 5, 20)
    results = collection.query(query_embeddings=question_numbers, n_results=candidate_limit)
    chunks = results["documents"][0]
    distances = results["distances"][0]

    # Give every chunk a score. A LOWER distance is better.
    ranked = []
    for chunk, distance in zip(chunks, distances):
        adjusted = distance - lexical_overlap_score(question, chunk) * 0.1
        low = 0
        if summary_mode:
            low = score_low_signal(chunk)
            adjusted = adjusted + low * 0.35 - score_high_signal(chunk) * 0.2
        ranked.append((adjusted, low, chunk))
    ranked.sort(key=first_item)

    # Drop chunks that look like references
    selected = []
    for adjusted, low, chunk in ranked:
        if low < 2:
            selected.append(chunk)

    if summary_mode:
        selected = get_opening_chunks(collection) + selected

    return dedupe_chunks(selected)[:max(top_k, 10)]