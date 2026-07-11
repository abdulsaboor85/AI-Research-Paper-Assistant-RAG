import re
import time
import nltk

from keybert import KeyBERT
from google import genai
from model_config import GEMINI_MODEL_POOL, MAX_RETRIES_PER_MODEL, RETRY_DELAY_SECONDS
from wordfreq import word_frequency
from nltk.tokenize import sent_tokenize, word_tokenize

for pkg in ("punkt", "punkt_tab", "wordnet", "omw-1.4"):
    nltk.download(pkg, quiet=True)

# Reuse the singleton from embedder - no second model load
print("[DifficultyScorer] Attaching KeyBERT to shared embedding model...")
from embedder import model as _EMBEDDING_MODEL
KW_MODEL = KeyBERT(model=_EMBEDDING_MODEL)
print("[DifficultyScorer] KeyBERT ready.")

DIFFICULTY_LABELS = [(3.5, "Easy"), (6.5, "Medium"), (10.0, "Hard")]

WEIGHTS = {
    "readability":     0.20,
    "uncommon_words":  0.15,
    "technical_terms": 0.25,
    "llm_perception":  0.40,
}

UNCOMMON_FREQ_THRESHOLD = 0.000008
KEYBERT_TOP_N       = 100
KEYBERT_NGRAM_RANGE = (1, 2)
KEYBERT_STOP_WORDS  = "english"
KEYBERT_DIVERSITY   = 0.7
KEYBERT_TEXT_LIMIT  = 8000
KEYBERT_MIN_SCORE   = 0.3


def _count_syllables(word: str) -> int:
    word = word.lower().strip(".,;:!?\"'")
    vowels, count, prev = "aeiouy", 0, False
    for ch in word:
        v = ch in vowels
        if v and not prev:
            count += 1
        prev = v
    if word.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


def compute_readability_score(text: str) -> tuple:
    sentences = sent_tokenize(text)
    words     = [w for w in word_tokenize(text) if w.isalpha()]
    if not sentences or not words:
        return 5.0, 5.0, 50.0
    asl = len(words) / len(sentences)
    asw = sum(_count_syllables(w) for w in words) / len(words)
    fk  = 0.39 * asl + 11.8 * asw - 15.59
    fre = max(0.0, min(100.0, 206.835 - 1.015 * asl - 84.6 * asw))
    fkd = min(10.0, max(0.0, (fk / 30.0) * 10.0))
    frd = min(10.0, max(0.0, (100.0 - fre) / 14.0))
    return round(fkd * 0.20 + frd * 0.80, 2), round(fk, 2), round(fre, 1)


def compute_uncommon_word_score(text: str, technical_words: set[str] | None = None) -> float:
    """
    Counts uncommon words, excluding technical/domain jargon already
    captured by the technical-terms component. This avoids double-penalizing
    the same vocabulary under two different labels.
    """
    technical_words = technical_words or set()
    words = [w for w in word_tokenize(text.lower()) if w.isalpha() and len(w) > 2]
    if not words:
        return 5.0
    unc = sum(
        1 for w in words
        if word_frequency(w, "en") < UNCOMMON_FREQ_THRESHOLD
        and w not in technical_words
    )
    return round(min(10.0, (unc / len(words)) * 20.0), 2)


def extract_technical_terms(text: str) -> list[tuple[str, float]]:
    try:
        kws = KW_MODEL.extract_keywords(
            text[:KEYBERT_TEXT_LIMIT],
            keyphrase_ngram_range=KEYBERT_NGRAM_RANGE,
            stop_words=KEYBERT_STOP_WORDS,
            top_n=KEYBERT_TOP_N,
            use_mmr=True,
            diversity=KEYBERT_DIVERSITY,
        )
        return [(kw, s) for kw, s in kws if s > KEYBERT_MIN_SCORE]
    except Exception as e:
        print(f"[KeyBERT] failed: {e}")
        return []


def compute_technical_term_score(text: str) -> tuple[float, int, list[str]]:
    words = [w for w in word_tokenize(text.lower()) if w.isalpha() and len(w) > 2]
    if not words:
        return 5.0, 0, []
    extracted = extract_technical_terms(text)
    if not extracted:
        return 0.0, 0, []
    term_words = {w.lower() for kp, _ in extracted for w in kp.split() if len(w) > 3}
    matched    = sum(1 for w in words if w in term_words)
    density    = matched / len(words)
    return round(min(10.0, (density / 0.20) * 10.0), 2), len(extracted), [kw for kw, _ in extracted]


def compute_llm_score(opening_text: str, api_key: str):
    """ASCII-only prints - no Unicode emoji - safe on Windows cp1252."""
    from google.genai import types as genai_types

    gemini_client = genai.Client(api_key=api_key)

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

    scores_collected = []

    for model_name in GEMINI_MODEL_POOL:
        for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
            try:
                print(f"[LLM] Trying {model_name} (attempt {attempt}/{MAX_RETRIES_PER_MODEL})...")
                resp = gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(temperature=0.0),
                )
                match = re.search(r'\b(\d+)\b', resp.text.strip())
                if match:
                    first_score = max(1, min(10, int(match.group(1))))
                    scores_collected.append(first_score)
                    print(f"[LLM] {model_name} -> score: {first_score}")

                    # Second confirmation call on the same model for stability
                    try:
                        resp2 = gemini_client.models.generate_content(
                            model=model_name,
                            contents=prompt,
                            config=genai_types.GenerateContentConfig(temperature=0.0),
                        )
                        match2 = re.search(r'\b(\d+)\b', resp2.text.strip())
                        if match2:
                            second_score = max(1, min(10, int(match2.group(1))))
                            scores_collected.append(second_score)
                            print(f"[LLM] {model_name} confirmation -> score: {second_score}")
                    except Exception as e2:
                        print(f"[LLM] Confirmation call failed, using single score: {e2}")

                    break  # got at least one valid score, stop retrying this model
            except Exception as e:
                err = str(e)
                if "429" in err or "quota" in err.lower():
                    print(f"[LLM] {model_name} quota exceeded - retrying in {RETRY_DELAY_SECONDS}s...")
                    time.sleep(RETRY_DELAY_SECONDS)
                elif "503" in err or "UNAVAILABLE" in err:
                    print(f"[LLM] {model_name} unavailable - retrying...")
                    time.sleep(RETRY_DELAY_SECONDS)
                elif "404" in err or "NOT_FOUND" in err.lower() or "invalid" in err.lower():
                    print(f"[LLM] {model_name} not found - next model...")
                    break
                else:
                    print(f"[LLM] {model_name} error: {e} - next model...")
                    break

        if scores_collected:
            break  # already have score(s) from this model, no need to try next one
        print(f"[LLM] Moving to next model...")

    if scores_collected:
        final_score = round(sum(scores_collected) / len(scores_collected))
        print(f"[LLM] Final averaged score: {scores_collected} -> {final_score}")
        return final_score

    print("[LLM] All models failed.")
    return None


def extract_opening_text(full_text: str) -> str:
    abs_m   = re.search(r'\bAbstract\b',              full_text, re.IGNORECASE)
    intro_m = re.search(r'\b(1\.?\s*)?Introduction\b', full_text, re.IGNORECASE)
    next_p  = re.compile(r'\b(2\.?\s*\w+|Related Work|Background|Methodology|Literature Review)\b', re.IGNORECASE)

    if abs_m and intro_m:
        nm  = next_p.search(full_text, intro_m.end())
        end = nm.start() if nm else intro_m.end() + 2000
        return full_text[abs_m.start():end].strip()
    elif abs_m:
        return full_text[abs_m.start():abs_m.start() + 2000].strip()
    elif intro_m:
        nm  = next_p.search(full_text, intro_m.end())
        end = nm.start() if nm else intro_m.end() + 2000
        return full_text[intro_m.start():end].strip()
    return full_text[:3000].strip()


def analyze_difficulty(full_text: str, api_key: str) -> dict:
    opening                          = extract_opening_text(full_text)
    r_score, fk_grade, fre_score     = compute_readability_score(full_text)
    t_score, kp_count, tech_terms    = compute_technical_term_score(full_text)
    technical_word_set               = {w.lower() for kp in tech_terms for w in kp.split()}
    u_score                          = compute_uncommon_word_score(full_text, technical_word_set)
    l_score                          = compute_llm_score(opening, api_key)

    if l_score is None:
        l_score = round((r_score + u_score + t_score) / 3, 1)
        print(f"[Fallback] LLM unavailable, estimated llm_perception={l_score} from algorithmic scores")

    final = round(
        r_score * WEIGHTS["readability"]     +
        u_score * WEIGHTS["uncommon_words"]  +
        t_score * WEIGHTS["technical_terms"] +
        l_score * WEIGHTS["llm_perception"], 2,
    )

    label = "Very Hard"
    for threshold, lbl in DIFFICULTY_LABELS:
        if final <= threshold:
            label = lbl
            break

    all_words = [w for w in word_tokenize(full_text.lower()) if w.isalpha() and len(w) > 2]
    unc_pct   = round(
        sum(1 for w in all_words if word_frequency(w, "en") < UNCOMMON_FREQ_THRESHOLD)
        / max(len(all_words), 1) * 100, 1,
    )

    return {
        "scores":          {"readability": r_score, "uncommon_words": u_score, "technical_terms": t_score, "llm_perception": l_score},
        "weights":         WEIGHTS,
        "final_score":     final,
        "difficulty_label": label,
        "breakdown": {
            "total_sentences":      len(sent_tokenize(full_text)),
            "total_words":          len(all_words),
            "uncommon_word_pct":    unc_pct,
            "technical_keyphrases": kp_count,
            "flesch_kincaid_grade": fk_grade,
            "flesch_reading_ease":  fre_score,
        },
    }