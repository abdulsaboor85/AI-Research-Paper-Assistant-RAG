"""
====================================================
 PATH  →  pipeline/difficulty_scorer.py
====================================================

FYP Module  : AI-Powered Research Paper Assistant (RAG)
Feature     : Difficulty Score Analysis
Author      : Abdul Saboor

Computes paper difficulty across 4 dimensions:

  1. Readability       — Flesch-Kincaid Grade Level (syllables + sentence length)
  2. Uncommon Words    — wordfreq real-world frequency (low freq = uncommon)
  3. Technical Terms   — KeyBERT keyword extraction using BAAI/bge-base-en-v1.5
                         (same model already loaded in embedder.py — no extra cost)
  4. LLM Perception    — Gemini model pool, tries each until one succeeds
"""

import re
import time
import nltk

from keybert import KeyBERT
from sentence_transformers import SentenceTransformer
from google import genai
from model_config import GEMINI_MODEL_POOL, MAX_RETRIES_PER_MODEL, RETRY_DELAY_SECONDS

from wordfreq import word_frequency
from nltk.corpus import words as nltk_words
from nltk.tokenize import sent_tokenize, word_tokenize

# ── NLTK one-time downloads ──────────────────────────────────────────────────
for pkg in ("words", "punkt", "punkt_tab", "wordnet", "omw-1.4"):
    nltk.download(pkg, quiet=True)

# ── NLTK common words corpus ─────────────────────────────────────────────────
COMMON_WORDS: set = {w.lower() for w in nltk_words.words()}

# ── KeyBERT — reuse the same embedding model already used by embedder.py ─────
# This means NO extra model download, NO extra memory beyond what's already loaded
print("  [DifficultyScorer] Loading KeyBERT with BAAI/bge-base-en-v1.5...")
_EMBEDDING_MODEL = SentenceTransformer("BAAI/bge-base-en-v1.5")
KW_MODEL = KeyBERT(model=_EMBEDDING_MODEL)
print("  [DifficultyScorer] KeyBERT ready.")

# ── Difficulty label thresholds ──────────────────────────────────────────────
DIFFICULTY_LABELS = [
    (3.5,  "Easy"),
    (6.5,  "Medium"),
    (10.0, "Hard"),
]

# ── Score weights (must sum to 1.0) ─────────────────────────────────────────
WEIGHTS = {
    "readability":     0.10,
    "uncommon_words":  0.10,
    "technical_terms": 0.10,
    "llm_perception":  0.70,
}

# ── wordfreq uncommon threshold ───────────────────────────────────────────────
UNCOMMON_FREQ_THRESHOLD = 0.000008

# ── KeyBERT extraction settings ──────────────────────────────────────────────
# top_n      : how many keywords to extract per paper
# keyphrase_ngram_range : (1,2) means single words AND two-word phrases
#                         e.g. "attention mechanism", "gradient descent"
# stop_words : removes common English words automatically
# diversity  : 0.7 means keywords are diverse (not all similar to each other)
KEYBERT_TOP_N              = 30
KEYBERT_NGRAM_RANGE        = (1, 2)
KEYBERT_STOP_WORDS         = "english"
KEYBERT_DIVERSITY          = 0.7
# Text limit sent to KeyBERT — first 8000 chars covers abstract + intro + body
KEYBERT_TEXT_LIMIT         = 8000


# ─────────────────────────────────────────────────────────────────────────────
#  HELPER: Syllable Counter
# ─────────────────────────────────────────────────────────────────────────────

def _count_syllables(word: str) -> int:
    """
    Heuristic syllable counter.
    Counts vowel groups, subtracts silent trailing 'e'.
    Returns minimum 1.
    """
    word = word.lower().strip(".,;:!?\"'")
    vowels = "aeiouy"
    count = 0
    prev_was_vowel = False

    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not prev_was_vowel:
            count += 1
        prev_was_vowel = is_vowel

    if word.endswith("e") and count > 1:
        count -= 1

    return max(1, count)


# ─────────────────────────────────────────────────────────────────────────────
#  COMPONENT 1: Readability Score (Flesch-Kincaid)
# ─────────────────────────────────────────────────────────────────────────────

def compute_readability_score(text: str) -> tuple:
    """
    Computes a readability difficulty score using both Flesch-Kincaid Grade
    Level and Flesch Reading Ease.

    Flesch-Kincaid Grade Level formula:
        FK = 0.39 * ASL + 11.8 * ASW - 15.59

    Flesch Reading Ease formula:
        FRE = 206.835 - 1.015 * ASL - 84.6 * ASW

    ASL = average sentence length (words per sentence)
    ASW = average syllables per word

    Returns:
        tuple: (readability_score, fk_grade, fre_score)
        - readability_score: 0-10 blended difficulty score
        - fk_grade: raw Flesch-Kincaid grade level
        - fre_score: 0-100 Flesch Reading Ease
    """
    sentences = sent_tokenize(text)
    words = [w for w in word_tokenize(text) if w.isalpha()]

    if not sentences or not words:
        return 5.0, 5.0, 50.0

    asl = len(words) / len(sentences)
    asw = sum(_count_syllables(w) for w in words) / len(words)

    fk_grade  = 0.39 * asl + 11.8 * asw - 15.59
    fre_score = max(0.0, min(100.0, 206.835 - 1.015 * asl - 84.6 * asw))

    fk_difficulty  = min(10.0, max(0.0, (fk_grade / 30.0) * 10.0))
    fre_difficulty = min(10.0, max(0.0, (100.0 - fre_score) / 14.0))

    readability_score = round((fk_difficulty * 0.20) + (fre_difficulty * 0.80), 2)

    return readability_score, round(fk_grade, 2), round(fre_score, 1)


# ─────────────────────────────────────────────────────────────────────────────
#  COMPONENT 2: Uncommon Word Score (wordfreq)
# ─────────────────────────────────────────────────────────────────────────────

def compute_uncommon_word_score(text: str) -> float:
    """
    Uses wordfreq to measure real-world English word frequency.
    A word is uncommon if its frequency is below UNCOMMON_FREQ_THRESHOLD.

    Calibration:
        0%  uncommon → score 0
        50%+ uncommon → score 10
    """
    words = [
        w for w in word_tokenize(text.lower())
        if w.isalpha() and len(w) > 2
    ]

    if not words:
        return 5.0

    uncommon_count = sum(
        1 for w in words
        if word_frequency(w, 'en') < UNCOMMON_FREQ_THRESHOLD
    )

    ratio = uncommon_count / len(words)
    score = min(10.0, ratio * 20.0)

    return round(score, 2)


# ─────────────────────────────────────────────────────────────────────────────
#  COMPONENT 3: Technical Term Score (KeyBERT)
# ─────────────────────────────────────────────────────────────────────────────

def extract_technical_terms(text: str) -> set[str]:
    """
    Uses KeyBERT with BAAI/bge-base-en-v1.5 to extract meaningful
    technical keywords and keyphrases from the paper.

    Why KeyBERT over scispaCy?
    - scispaCy is trained on biomedical text only — it misses CS/ML terms
      like "softmax", "encoder", "attention", "gradient descent" entirely.
    - KeyBERT is domain-agnostic — it uses embedding similarity to find
      the most semantically important terms in ANY paper regardless of field.
    - We reuse the same BAAI/bge-base-en-v1.5 model already loaded in
      embedder.py, so there is zero extra memory or download cost.

    Returns:
        set of unique technical keyword strings extracted from the paper
    """
    # Use first KEYBERT_TEXT_LIMIT chars — covers abstract + intro + body start
    sample_text = text[:KEYBERT_TEXT_LIMIT]

    try:
        keywords = KW_MODEL.extract_keywords(
            sample_text,
            keyphrase_ngram_range=KEYBERT_NGRAM_RANGE,
            stop_words=KEYBERT_STOP_WORDS,
            top_n=KEYBERT_TOP_N,
            use_mmr=True,          # MMR = Maximal Marginal Relevance
                                   # ensures diverse keywords, not repetitive ones
            diversity=KEYBERT_DIVERSITY,
        )

        # keywords is a list of (keyword_string, relevance_score) tuples
        # We only keep keywords with a relevance score above 0.3
        # to filter out weak/generic matches
        technical_terms = {
            kw for kw, score in keywords
            if score > 0.3
        }

        return technical_terms

    except Exception as e:
        print(f"  [KeyBERT] extraction failed: {e}")
        return set()


def compute_technical_term_score(text: str) -> float:
    """
    Scores technical density using KeyBERT keyword extraction.

    How it works:
    1. KeyBERT extracts the top 30 most technically significant
       keywords/keyphrases from the paper using embedding similarity.
    2. We count unique terms found.
    3. We normalize against total word count to get a density ratio.
    4. Density is scaled to 0-10.

    Calibration:
        0    unique technical terms → score 0
        20%+ unique technical terms → score 10

    This replaces scispaCy which was domain-locked to biomedical text.
    """
    words = [
        w for w in word_tokenize(text.lower())
        if w.isalpha() and len(w) > 2
    ]

    if not words:
        return 5.0

    technical_terms = extract_technical_terms(text)

    if not technical_terms:
        return 0.0

    # Count how many tokens in the full text match our extracted terms
    # This gives us a proper density measure rather than just counting
    # the number of unique terms
    term_words = set()
    for term in technical_terms:
        for word in term.split():
            if len(word) > 3:
                term_words.add(word.lower())

    matched_tokens = sum(1 for w in words if w in term_words)
    density = matched_tokens / len(words)

    score = min(10.0, (density / 0.20) * 10.0)

    return round(score, 2)


# ─────────────────────────────────────────────────────────────────────────────
#  COMPONENT 4: LLM Perception Score (Shared Gemini Model Pool)
# ─────────────────────────────────────────────────────────────────────────────

def compute_llm_score(opening_text: str, api_key: str) -> int:
    """
    Sends the opening portion of the paper to Gemini for difficulty assessment.

    Uses shared GEMINI_MODEL_POOL from model_config.py — tries each model
    in order of quota availability. Falls back to 5 only if every model fails.

    Pool order (by free RPD, highest first):
        1. gemini-3.1-flash-lite  →  500 RPD
        2. gemini-2.5-flash       →   23 RPD
        3. gemini-3-flash         →   20 RPD
        4. gemini-2.5-flash-lite  →   20 RPD

    Args:
        opening_text (str): The abstract/introduction portion of the paper
        api_key (str): Gemini API key

    Returns:
        int: Difficulty score 1-10 (or 5 if all models fail)
    """
    client = genai.Client(api_key=api_key)

    prompt = f"""You are an expert academic evaluator assessing research paper difficulty.

Below is the opening section of a research paper.
Rate how difficult this paper is to understand on a scale of 1 to 10.

Scale:
  1-2  = Very easy (plain English, no prior knowledge needed)
  3-4  = Easy (undergraduate level, clear explanations)
  5-6  = Moderate (graduate level, some domain knowledge assumed)
  7-8  = Hard (expert audience, dense concepts and notation)
  9-10 = Very hard (highly specialized, assumes deep domain expertise)

Consider:
- Conceptual complexity and abstraction level
- Density of ideas per paragraph
- Amount of assumed prior knowledge
- Use of specialized notation or formalism
- Vocabulary complexity

Paper Opening:
{opening_text[:3000]}

IMPORTANT: Respond with ONLY a single integer between 1 and 10. No explanation. No extra words."""

    for model_name in GEMINI_MODEL_POOL:
        for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
            try:
                print(f"  [LLM] Trying {model_name} (attempt {attempt}/{MAX_RETRIES_PER_MODEL})...")

                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )

                raw = response.text.strip()
                match = re.search(r'\b(\d+)\b', raw)

                if match:
                    score = max(1, min(10, int(match.group(1))))
                    print(f"  [LLM] {model_name} responded -> score: {score}")
                    return score

            except Exception as e:
                error_msg = str(e)

                if "429" in error_msg or "quota" in error_msg.lower():
                    print(f"  [LLM] {model_name} quota exceeded (attempt {attempt}/{MAX_RETRIES_PER_MODEL}). Retrying in {RETRY_DELAY_SECONDS}s...")
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue

                elif "503" in error_msg or "UNAVAILABLE" in error_msg:
                    print(f"  [LLM] {model_name} unavailable (attempt {attempt}/{MAX_RETRIES_PER_MODEL}). Retrying in {RETRY_DELAY_SECONDS}s...")
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue

                elif "404" in error_msg or "NOT_FOUND" in error_msg.lower():
                    print(f"  [LLM] {model_name} not found -> trying next model...")
                    break

                elif "invalid" in error_msg.lower():
                    print(f"  [LLM] {model_name} invalid -> trying next model...")
                    break

                else:
                    print(f"  [LLM] {model_name} failed: {e}")
                    break

        print(f"  [LLM] Moving to next model in pool...")

    print(f"  [LLM] All models exhausted. Using fallback score of 5.")
    return 5


# ─────────────────────────────────────────────────────────────────────────────
#  SECTION EXTRACTOR
# ─────────────────────────────────────────────────────────────────────────────

def extract_opening_text(full_text: str) -> str:
    """
    Extracts the most useful opening portion of the paper for LLM scoring.

    Strategy:
      1. Both Abstract + Introduction headings found -> slice that range
      2. Only one heading found -> slice from that heading
      3. No headings found -> use first 3000 chars of raw text
    """
    abstract_pattern     = re.compile(r'\bAbstract\b', re.IGNORECASE)
    intro_pattern        = re.compile(r'\b(1\.?\s*)?Introduction\b', re.IGNORECASE)
    next_section_pattern = re.compile(
        r'\b(2\.?\s*\w+|Related Work|Background|Methodology|Literature Review)\b',
        re.IGNORECASE
    )

    abs_match   = abstract_pattern.search(full_text)
    intro_match = intro_pattern.search(full_text)

    if abs_match and intro_match:
        next_match = next_section_pattern.search(full_text, intro_match.end())
        intro_end  = next_match.start() if next_match else intro_match.end() + 2000
        opening    = full_text[abs_match.start():intro_end].strip()

    elif abs_match:
        opening = full_text[abs_match.start():abs_match.start() + 2000].strip()

    elif intro_match:
        next_match = next_section_pattern.search(full_text, intro_match.end())
        intro_end  = next_match.start() if next_match else intro_match.end() + 2000
        opening    = full_text[intro_match.start():intro_end].strip()

    else:
        opening = full_text[:3000].strip()

    return opening


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN: analyze_difficulty()
# ─────────────────────────────────────────────────────────────────────────────

def analyze_difficulty(full_text: str, api_key: str) -> dict:
    """
    Main entry point for the Difficulty Score feature.

    Args:
        full_text (str) : Full extracted paper text from PyMuPDF / pdfplumber
        api_key   (str) : Gemini API key loaded from .env

    Returns:
        dict: {
            "scores": {
                "readability":     float,   # 0.0 - 10.0
                "uncommon_words":  float,   # 0.0 - 10.0
                "technical_terms": float,   # 0.0 - 10.0
                "llm_perception":  int,     # 1 - 10
            },
            "weights":          dict,
            "final_score":      float,      # 0.0 - 10.0
            "difficulty_label": str,        # Easy / Medium / Hard / Very Hard
            "breakdown": {
                "total_sentences":      int,
                "total_words":          int,
                "uncommon_word_pct":    float,
                "technical_term_pct":   float,
                "flesch_kincaid_grade": float,
                "flesch_reading_ease":  float,
            }
        }
    """

    # ── Extract opening text for LLM ─────────────────────────────────────────
    opening_text = extract_opening_text(full_text)

    # ── Compute all component scores ──────────────────────────────────────────
    r_score, fk_grade, fre_score = compute_readability_score(full_text)
    u_score  = compute_uncommon_word_score(full_text)
    t_score  = compute_technical_term_score(full_text)
    l_score  = compute_llm_score(opening_text, api_key)

    # ── Weighted final score ──────────────────────────────────────────────────
    final = round(
        r_score * WEIGHTS["readability"]     +
        u_score * WEIGHTS["uncommon_words"]  +
        t_score * WEIGHTS["technical_terms"] +
        l_score * WEIGHTS["llm_perception"],
        2
    )

    # ── Difficulty label ──────────────────────────────────────────────────────
    label = "Very Hard"
    for threshold, lbl in DIFFICULTY_LABELS:
        if final <= threshold:
            label = lbl
            break

    # ── Breakdown stats ───────────────────────────────────────────────────────
    all_words = [
        w for w in word_tokenize(full_text.lower())
        if w.isalpha() and len(w) > 2
    ]
    sentences = sent_tokenize(full_text)

    uncommon_pct = round(
        sum(
            1 for w in all_words
            if word_frequency(w, 'en') < UNCOMMON_FREQ_THRESHOLD
        ) / max(len(all_words), 1) * 100,
        1
    )

    technical_terms = extract_technical_terms(full_text)
    technical_pct   = round(len(technical_terms) / max(len(all_words), 1) * 100, 1)

    return {
        "scores": {
            "readability":     r_score,
            "uncommon_words":  u_score,
            "technical_terms": t_score,
            "llm_perception":  l_score,
        },
        "weights":          WEIGHTS,
        "final_score":      final,
        "difficulty_label": label,
        "breakdown": {
            "total_sentences":      len(sentences),
            "total_words":          len(all_words),
            "uncommon_word_pct":    uncommon_pct,
            "technical_term_pct":   technical_pct,
            "flesch_kincaid_grade": fk_grade,
            "flesch_reading_ease":  fre_score,
        },
    }