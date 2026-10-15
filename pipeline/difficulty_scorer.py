"""Difficulty score = readability + uncommon words + technical terms + LLM opinion."""

import re

import nltk
from keybert import KeyBERT
from nltk.tokenize import sent_tokenize, word_tokenize
from wordfreq import word_frequency

from embedder import model as _EMBEDDING_MODEL  # reuse the shared model
from model_config import call_gemini
from personalization import difficulty_label

for pkg in ("punkt", "punkt_tab", "wordnet", "omw-1.4"):
    nltk.download(pkg, quiet=True)

KW_MODEL = KeyBERT(model=_EMBEDDING_MODEL)

WEIGHTS = {
    "readability": 0.20,
    "uncommon_words": 0.15,
    "technical_terms": 0.25,
    "llm_perception": 0.40,
}

UNCOMMON_FREQ_THRESHOLD = 0.000008
KEYBERT_TOP_N = 100
KEYBERT_TEXT_LIMIT = 8000
KEYBERT_MIN_SCORE = 0.3


def _clean_words(text: str) -> list[str]:
    """Lowercase alphabetic words longer than 2 letters."""
    return [w for w in word_tokenize(text.lower()) if w.isalpha() and len(w) > 2]


def _count_syllables(word: str) -> int:
    word = word.lower().strip(".,;:!?\"'")
    count, previous_was_vowel = 0, False
    for ch in word:
        is_vowel = ch in "aeiouy"
        if is_vowel and not previous_was_vowel:
            count += 1
        previous_was_vowel = is_vowel
    if word.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


# ── 1. Readability ───────────────────────────────────────

def compute_readability_score(text: str) -> tuple[float, float, float]:
    """Returns (score 0-10, Flesch-Kincaid grade, Flesch reading ease)."""
    sentences = sent_tokenize(text)
    words = [w for w in word_tokenize(text) if w.isalpha()]
    if not sentences or not words:
        return 5.0, 5.0, 50.0

    words_per_sentence = len(words) / len(sentences)
    syllables_per_word = sum(_count_syllables(w) for w in words) / len(words)

    fk_grade = 0.39 * words_per_sentence + 11.8 * syllables_per_word - 15.59
    reading_ease = max(0.0, min(100.0, 206.835 - 1.015 * words_per_sentence - 84.6 * syllables_per_word))

    grade_part = min(10.0, max(0.0, fk_grade / 30.0 * 10.0))
    ease_part = min(10.0, max(0.0, (100.0 - reading_ease) / 14.0))
    return round(grade_part * 0.20 + ease_part * 0.80, 2), round(fk_grade, 2), round(reading_ease, 1)


# ── 2. Technical terms (KeyBERT) ─────────────────────────

def extract_technical_terms(text: str) -> list[str]:
    try:
        keywords = KW_MODEL.extract_keywords(
            text[:KEYBERT_TEXT_LIMIT],
            keyphrase_ngram_range=(1, 2),
            stop_words="english",
            top_n=KEYBERT_TOP_N,
            use_mmr=True,
            diversity=0.7,
        )
        return [kw for kw, score in keywords if score > KEYBERT_MIN_SCORE]
    except Exception as e:
        print(f"[KeyBERT] failed: {e}")
        return []


def compute_technical_term_score(words: list[str], terms: list[str]) -> float:
    if not words:
        return 5.0
    if not terms:
        return 0.0
    term_words = {w.lower() for term in terms for w in term.split() if len(w) > 3}
    density = sum(1 for w in words if w in term_words) / len(words)
    return round(min(10.0, density / 0.20 * 10.0), 2)


# ── 3. Uncommon words ────────────────────────────────────

def _is_uncommon(word: str) -> bool:
    return word_frequency(word, "en") < UNCOMMON_FREQ_THRESHOLD


def compute_uncommon_word_score(words: list[str], technical_words: set[str]) -> float:
    """Uncommon words, excluding technical jargon (already counted in technical terms)."""
    if not words:
        return 5.0
    uncommon = sum(1 for w in words if _is_uncommon(w) and w not in technical_words)
    return round(min(10.0, uncommon / len(words) * 20.0), 2)


# ── 4. LLM opinion ───────────────────────────────────────

def extract_opening_text(full_text: str) -> str:
    """Abstract + introduction (or the first 3000 characters)."""
    abstract = re.search(r"\bAbstract\b", full_text, re.IGNORECASE)
    intro = re.search(r"\b(1\.?\s*)?Introduction\b", full_text, re.IGNORECASE)
    next_section = re.compile(
        r"\b(2\.?\s*\w+|Related Work|Background|Methodology|Literature Review)\b", re.IGNORECASE
    )

    if abstract and intro:
        found = next_section.search(full_text, intro.end())
        end = found.start() if found else intro.end() + 2000
        return full_text[abstract.start():end].strip()
    if abstract:
        return full_text[abstract.start():abstract.start() + 2000].strip()
    if intro:
        found = next_section.search(full_text, intro.end())
        end = found.start() if found else intro.end() + 2000
        return full_text[intro.start():end].strip()
    return full_text[:3000].strip()


def compute_llm_score(opening_text: str, api_key: str) -> int | None:
    prompt = f"""You are a strict academic difficulty evaluator.
Rate the difficulty of this research paper opening from 1 to 10.

SCALE:
  1-2  = Beginner. Plain English, no background needed.
  3-4  = Undergraduate. Basic math/programming assumed.
  5-6  = Graduate. Assumes field foundations, dense with ideas.
  7-8  = Expert. Novel methods, heavy formalism, deep domain needed.
  9-10 = Highly specialized. Mastery of multiple subfields required.

RULES:
- Novel model/method/architecture proposed -> score at least 7.
- Applying existing methods to new data -> score 5-6.
- Heavy math/proofs -> add 1-2.
- Most published papers score 6-9.

Paper Opening:
{opening_text[:3000]}

Reply with ONLY a single integer from 1 to 10."""

    try:
        reply = call_gemini(prompt, api_key, temperature=0.0, tag="LLM")
    except Exception as e:
        print(f"[LLM] All models failed: {e}")
        return None

    match = re.search(r"\b(\d+)\b", reply)
    return max(1, min(10, int(match.group(1)))) if match else None


# ── Main ─────────────────────────────────────────────────

def analyze_difficulty(full_text: str, api_key: str) -> dict:
    words = _clean_words(full_text)

    readability, fk_grade, reading_ease = compute_readability_score(full_text)
    terms = extract_technical_terms(full_text)
    technical = compute_technical_term_score(words, terms)
    technical_words = {w.lower() for term in terms for w in term.split()}
    uncommon = compute_uncommon_word_score(words, technical_words)

    llm = compute_llm_score(extract_opening_text(full_text), api_key)
    if llm is None:
        llm = round((readability + uncommon + technical) / 3, 1)
        print(f"[Fallback] LLM unavailable, estimated llm_perception={llm}")

    scores = {
        "readability": readability,
        "uncommon_words": uncommon,
        "technical_terms": technical,
        "llm_perception": llm,
    }
    final = round(sum(scores[key] * WEIGHTS[key] for key in WEIGHTS), 2)

    uncommon_pct = round(sum(1 for w in words if _is_uncommon(w)) / max(len(words), 1) * 100, 1)

    return {
        "scores": scores,
        "weights": WEIGHTS,
        "final_score": final,
        "difficulty_label": difficulty_label(final),
        "breakdown": {
            "total_sentences": len(sent_tokenize(full_text)),
            "total_words": len(words),
            "uncommon_word_pct": uncommon_pct,
            "technical_keyphrases": len(terms),
            "technical_terms_list": terms,
            "flesch_kincaid_grade": fk_grade,
            "flesch_reading_ease": reading_ease,
        },
    }