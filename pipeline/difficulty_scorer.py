"""
====================================================
 PATH  ->  pipeline/difficulty_scorer.py
====================================================

FYP Module  : AI-Powered Research Paper Assistant (RAG)
Feature     : Difficulty Score Analysis
Author      : Abdul Saboor

Computes paper difficulty across 4 dimensions:

  1. Readability       -- Flesch-Kincaid Grade Level + Flesch Reading Ease
  2. Uncommon Words    -- wordfreq real-world frequency
  3. Technical Terms   -- KeyBERT with BAAI/bge-base-en-v1.5 (same model as embedder)
  4. LLM Perception    -- Gemini model pool with retry + fallback logic
"""

import re
import time
import nltk

from keybert import KeyBERT
from sentence_transformers import SentenceTransformer
from google import genai
from model_config import GEMINI_MODEL_POOL, MAX_RETRIES_PER_MODEL, RETRY_DELAY_SECONDS

from wordfreq import word_frequency
from nltk.tokenize import sent_tokenize, word_tokenize

# ── NLTK one-time downloads ──────────────────────────────────────────────────
for pkg in ("punkt", "punkt_tab", "wordnet", "omw-1.4"):
    nltk.download(pkg, quiet=True)

# ── KeyBERT — reuses BAAI/bge-base-en-v1.5 already used in embedder.py ──────
# No extra model download. No extra memory cost.
print("  [DifficultyScorer] Loading KeyBERT with BAAI/bge-base-en-v1.5...")
_EMBEDDING_MODEL = SentenceTransformer("BAAI/bge-base-en-v1.5")
KW_MODEL         = KeyBERT(model=_EMBEDDING_MODEL)
print("  [DifficultyScorer] KeyBERT ready.")

# ── Difficulty label thresholds ──────────────────────────────────────────────
DIFFICULTY_LABELS = [
    (3.5,  "Easy"),
    (6.5,  "Medium"),
    (10.0, "Hard"),
]

# ── Score weights (must sum to 1.0) ──────────────────────────────────────────
WEIGHTS = {
    "readability":     0.10,
    "uncommon_words":  0.10,
    "technical_terms": 0.10,
    "llm_perception":  0.70,
}

# ── wordfreq threshold — words below this frequency are uncommon ──────────────
# "neural"            -> 0.000008  (uncommon, counted)
# "backpropagation"   -> 0.0000004 (uncommon, counted)
# "learning"          -> 0.00012   (common,   ignored)
UNCOMMON_FREQ_THRESHOLD = 0.000008

# ── KeyBERT settings ──────────────────────────────────────────────────────────
KEYBERT_TOP_N        = 30        # extract top 30 keyphrases per paper
KEYBERT_NGRAM_RANGE  = (1, 2)   # single words AND two-word phrases
KEYBERT_STOP_WORDS   = "english" # auto-remove common English words
KEYBERT_DIVERSITY    = 0.7       # MMR diversity — avoids repetitive results
KEYBERT_TEXT_LIMIT   = 8000      # chars sent to KeyBERT (abstract + intro + body start)
KEYBERT_MIN_SCORE    = 0.3       # minimum relevance score to keep a keyphrase


# ─────────────────────────────────────────────────────────────────────────────
#  HELPER: Syllable Counter
# ─────────────────────────────────────────────────────────────────────────────

def _count_syllables(word: str) -> int:
    """
    Heuristic syllable counter.
    Counts vowel groups, subtracts silent trailing 'e'.
    Returns minimum 1.
    """
    word           = word.lower().strip(".,;:!?\"'")
    vowels         = "aeiouy"
    count          = 0
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
    Blends Flesch-Kincaid Grade Level and Flesch Reading Ease into
    a single 0-10 difficulty score.

    FK Grade  = 0.39 * ASL + 11.8 * ASW - 15.59
    FRE Score = 206.835 - 1.015 * ASL - 84.6 * ASW

    ASL = average sentence length (words per sentence)
    ASW = average syllables per word

    Returns:
        tuple: (readability_score 0-10, fk_grade raw, fre_score 0-100)
    """
    sentences = sent_tokenize(text)
    words     = [w for w in word_tokenize(text) if w.isalpha()]

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
    Uses wordfreq real-world frequency to identify uncommon words.
    Words below UNCOMMON_FREQ_THRESHOLD are counted as uncommon.

    Calibration:
        0%   uncommon words -> score 0
        50%+ uncommon words -> score 10
    """
    words = [
        w for w in word_tokenize(text.lower())
        if w.isalpha() and len(w) > 2
    ]

    if not words:
        return 5.0

    uncommon_count = sum(
        1 for w in words
        if word_frequency(w, "en") < UNCOMMON_FREQ_THRESHOLD
    )

    ratio = uncommon_count / len(words)
    score = min(10.0, ratio * 20.0)

    return round(score, 2)


# ─────────────────────────────────────────────────────────────────────────────
#  COMPONENT 3: Technical Term Score (KeyBERT)
# ─────────────────────────────────────────────────────────────────────────────

def extract_technical_terms(text: str) -> list[tuple[str, float]]:
    """
    Uses KeyBERT with BAAI/bge-base-en-v1.5 to extract meaningful
    technical keywords and keyphrases from the paper.

    Why KeyBERT instead of scispaCy:
    - scispaCy is trained only on biomedical text. It misses CS/ML terms
      like softmax, encoder, attention, gradient descent completely.
    - KeyBERT uses embedding similarity and is fully domain-agnostic.
      It finds the most semantically important terms in ANY paper.
    - We reuse the same model already loaded in embedder.py so there
      is zero extra memory or download cost.

    Returns:
        list of (keyphrase, relevance_score) tuples above KEYBERT_MIN_SCORE
    """
    sample_text = text[:KEYBERT_TEXT_LIMIT]

    try:
        keywords = KW_MODEL.extract_keywords(
            sample_text,
            keyphrase_ngram_range=KEYBERT_NGRAM_RANGE,
            stop_words=KEYBERT_STOP_WORDS,
            top_n=KEYBERT_TOP_N,
            use_mmr=True,
            diversity=KEYBERT_DIVERSITY,
        )

        return [(kw, score) for kw, score in keywords if score > KEYBERT_MIN_SCORE]

    except Exception as e:
        print(f"  [KeyBERT] extraction failed: {e}")
        return []


def compute_technical_term_score(text: str) -> tuple[float, int, list[str]]:
    """
    Scores technical density using KeyBERT keyword extraction.

    Steps:
    1. KeyBERT extracts top 30 keyphrases using embedding similarity.
    2. Individual words from each keyphrase are collected into a term-word set.
    3. Count how many tokens in the full text match those term-words.
    4. Density = matched tokens / total tokens, scaled to 0-10.

    Calibration:
        0    technical density -> score 0
        20%+ technical density -> score 10

    Returns:
        tuple: (score 0-10, unique_keyphrases_count, keyphrases_list)
    """
    words = [
        w for w in word_tokenize(text.lower())
        if w.isalpha() and len(w) > 2
    ]

    if not words:
        return 5.0, 0, []

    extracted = extract_technical_terms(text)

    if not extracted:
        return 0.0, 0, []

    # Collect individual words from all keyphrases (length > 3 to skip noise)
    term_words = set()
    for keyphrase, _ in extracted:
        for word in keyphrase.split():
            if len(word) > 3:
                term_words.add(word.lower())

    matched_tokens = sum(1 for w in words if w in term_words)
    density        = matched_tokens / len(words)
    score          = min(10.0, (density / 0.20) * 10.0)
    keyphrases     = [kw for kw, _ in extracted]

    return round(score, 2), len(extracted), keyphrases


# ─────────────────────────────────────────────────────────────────────────────
#  COMPONENT 4: LLM Perception Score (Gemini Model Pool)
# ─────────────────────────────────────────────────────────────────────────────

def compute_llm_score(opening_text: str, api_key: str) -> int:
    """
    Sends the opening portion of the paper to Gemini for difficulty assessment.

    Uses shared GEMINI_MODEL_POOL from model_config.py.
    Tries each model in order. Falls back to 5 if every model fails.

    The scale is carefully worded to produce accurate ratings:
    - Papers proposing novel architectures score 7-8 (deep prior knowledge needed)
    - Papers applying existing methods score 5-6
    - Heavy math/notation papers add 1-2 to the base score

    Args:
        opening_text (str): Abstract + introduction of the paper
        api_key      (str): Gemini API key

    Returns:
        int: Difficulty score 1-10 (fallback 5 if all models fail)
    """
    client = genai.Client(api_key=api_key)

    prompt = f"""You are a strict academic difficulty evaluator assessing research papers.

Read the opening section of this research paper and rate how difficult it is
for a reader to fully understand on a scale of 1 to 10.

SCALE DEFINITION (read carefully before scoring):
  1-2  = Beginner friendly. Plain English. No technical background needed.
          Example: a blog post explaining what machine learning is.
  3-4  = Undergraduate level. Concepts are explained as they are introduced.
          Assumes basic math and programming knowledge only.
          Example: an introductory ML textbook chapter.
  5-6  = Graduate level. Assumes the reader already knows the field foundations.
          Uses technical terms without defining them. Dense with ideas.
          Example: a survey paper summarizing existing methods.
  7-8  = Expert level. Proposes novel methods or architectures.
          Assumes deep domain expertise. Heavy notation and formalism.
          Requires significant prior reading to understand.
          Example: a paper introducing a new neural architecture like Transformers.
  9-10 = Highly specialized. Assumes mastery of multiple advanced subfields.
          Incomprehensible without years of domain expertise.
          Example: a theoretical proof-heavy paper in a niche research area.

SCORING RULES:
- If the paper PROPOSES something new (new model, method, architecture),
  score at least 7 because understanding it requires knowing what came before.
- If the paper APPLIES existing methods to a new dataset, score 5-6.
- If the paper is heavy with mathematical notation or formal proofs, add 1-2.
- Do NOT be overly conservative. Most published research papers score 6-9.

Paper Opening:
{opening_text[:3000]}

IMPORTANT: Reply with ONLY a single integer from 1 to 10. No explanation. No extra text."""

    for model_name in GEMINI_MODEL_POOL:
        for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
            try:
                print(f"  [LLM] Trying {model_name} (attempt {attempt}/{MAX_RETRIES_PER_MODEL})...")

                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )

                raw   = response.text.strip()
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

    print("  [LLM] All models exhausted. Using fallback score of 5.")
    return 5


# ─────────────────────────────────────────────────────────────────────────────
#  SECTION EXTRACTOR
# ─────────────────────────────────────────────────────────────────────────────

def extract_opening_text(full_text: str) -> str:
    """
    Extracts the most useful opening portion of the paper for LLM scoring.

    Strategy:
      1. Both Abstract + Introduction found -> slice that full range
      2. Only one heading found -> slice from that heading
      3. No headings -> use first 3000 chars
    """
    abstract_pattern     = re.compile(r'\bAbstract\b',              re.IGNORECASE)
    intro_pattern        = re.compile(r'\b(1\.?\s*)?Introduction\b', re.IGNORECASE)
    next_section_pattern = re.compile(
        r'\b(2\.?\s*\w+|Related Work|Background|Methodology|Literature Review)\b',
        re.IGNORECASE,
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
        full_text (str) : Full extracted paper text
        api_key   (str) : Gemini API key from .env

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
                "total_sentences":       int,
                "total_words":           int,
                "uncommon_word_pct":     float,
                "technical_keyphrases":  int,   # count of unique keyphrases found
                "flesch_kincaid_grade":  float,
                "flesch_reading_ease":   float,
            }
        }
    """

    # ── Extract opening text for LLM ─────────────────────────────────────────
    opening_text = extract_opening_text(full_text)

    # ── Compute all four component scores ────────────────────────────────────
    r_score, fk_grade, fre_score          = compute_readability_score(full_text)
    u_score                               = compute_uncommon_word_score(full_text)
    t_score, keyphrases_count, _          = compute_technical_term_score(full_text)
    l_score                               = compute_llm_score(opening_text, api_key)

    # ── Weighted final score ──────────────────────────────────────────────────
    final = round(
        r_score * WEIGHTS["readability"]     +
        u_score * WEIGHTS["uncommon_words"]  +
        t_score * WEIGHTS["technical_terms"] +
        l_score * WEIGHTS["llm_perception"],
        2,
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
            if word_frequency(w, "en") < UNCOMMON_FREQ_THRESHOLD
        ) / max(len(all_words), 1) * 100,
        1,
    )

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
            "technical_keyphrases": keyphrases_count,
            "flesch_kincaid_grade": fk_grade,
            "flesch_reading_ease":  fre_score,
        },
    }