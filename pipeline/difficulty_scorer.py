"""
difficulty_scorer.py  -  how HARD is a paper? A score from 0 to 10.

HOW THIS FILE WORKS (easy words)
------------------------------------------------------------
The final score mixes FOUR smaller scores (each is 0 to 10):
  1. Readability (20%)      long sentences and long words = harder (Flesch-Kincaid)
  2. Uncommon words (15%)   many rare words = harder
  3. Technical terms (25%)  many technical key phrases (found by KeyBERT) = harder
  4. AI opinion (40%)       Gemini reads the abstract + introduction and gives 1-10.
                            We ask TWICE and take the average.
final = (readability x 0.20) + (uncommon x 0.15) + (technical x 0.25) + (AI x 0.40)
If Gemini is not available, we guess the AI score from the other three.

FUNCTION GUIDE
------------------------------------------------------------
   download_nltk_data         download the small language data files (first run only)
   count_syllables            how many syllables a word has
   readability_score          score 1: readability
   get_content_words          the words of the text (lowercase, letters only)
   uncommon_score             score 2: uncommon words
   find_keyphrases            find technical key phrases with KeyBERT
   technical_score            score 3: technical terms
   llm_score                  score 4: ask Gemini for a difficulty from 1 to 10
   find_opening_text          the abstract + introduction of the paper
   analyze_difficulty         the main function: puts everything together
"""

import re

import nltk
from keybert import KeyBERT
from nltk.tokenize import sent_tokenize, word_tokenize
from wordfreq import word_frequency

from embedder import model as embedding_model
from model_config import generate_text
from personalization import difficulty_label


def download_nltk_data():
    for package, path in [("punkt", "tokenizers/punkt"), ("punkt_tab", "tokenizers/punkt_tab")]:
        try:
            nltk.data.find(path)
        except LookupError:
            nltk.download(package, quiet=True)


download_nltk_data()
keyword_model = KeyBERT(model=embedding_model)

WEIGHTS = {"readability": 0.20, "uncommon_words": 0.15, "technical_terms": 0.25, "llm_perception": 0.40}

RARE_WORD_LIMIT = 0.000008     # a word rarer than this is "uncommon"
KEYBERT_TOP_N = 100
KEYBERT_TEXT_LIMIT = 8000      # only the first 8000 letters are used for key phrases
KEYBERT_MIN_SCORE = 0.3

# where the introduction ends (the next section starts)
NEXT_SECTION = re.compile(r"\b(2\.?\s*\w+|Related Work|Background|Methodology|Literature Review)\b", re.IGNORECASE)


# ---------------------------------------------------------------
# Score 1: readability
# ---------------------------------------------------------------
def count_syllables(word):
    word = word.lower().strip(".,;:!?\"'")
    count = 0
    last_was_vowel = False
    for letter in word:
        is_vowel = letter in "aeiouy"
        if is_vowel and not last_was_vowel:
            count += 1
        last_was_vowel = is_vowel
    if word.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


def readability_score(text):
    """Returns (score 0-10, Flesch-Kincaid grade, Flesch reading ease)."""
    sentences = sent_tokenize(text)
    words = []
    for word in word_tokenize(text):
        if word.isalpha():
            words.append(word)
    if not sentences or not words:
        return 5.0, 5.0, 50.0

    words_per_sentence = len(words) / len(sentences)
    total_syllables = 0
    for word in words:
        total_syllables += count_syllables(word)
    syllables_per_word = total_syllables / len(words)

    grade = 0.39 * words_per_sentence + 11.8 * syllables_per_word - 15.59
    ease = 206.835 - 1.015 * words_per_sentence - 84.6 * syllables_per_word
    ease = max(0.0, min(100.0, ease))

    grade_score = min(10.0, max(0.0, (grade / 30.0) * 10.0))
    ease_score = min(10.0, max(0.0, (100.0 - ease) / 14.0))
    return round(grade_score * 0.20 + ease_score * 0.80, 2), round(grade, 2), round(ease, 1)


# ---------------------------------------------------------------
# Score 2: uncommon words
# ---------------------------------------------------------------
def get_content_words(text):
    words = []
    for word in word_tokenize(text.lower()):
        if word.isalpha() and len(word) > 2:
            words.append(word)
    return words


def uncommon_score(words, uncommon_words, technical_words):
    """Uncommon words WITHOUT technical words (those are counted in score 3)."""
    if not words:
        return 5.0
    count = 0
    for word in uncommon_words:
        if word not in technical_words:
            count += 1
    return round(min(10.0, (count / len(words)) * 20.0), 2)


# ---------------------------------------------------------------
# Score 3: technical terms
# ---------------------------------------------------------------
def find_keyphrases(text):
    """The technical key phrases of the paper (a list of texts)."""
    try:
        found = keyword_model.extract_keywords(text[:KEYBERT_TEXT_LIMIT], keyphrase_ngram_range=(1, 2),
                                               stop_words="english", top_n=KEYBERT_TOP_N,
                                               use_mmr=True, diversity=0.7)
    except Exception as error:
        print("[KeyBERT] failed:", error)
        return []

    phrases = []
    for phrase, score in found:
        if score > KEYBERT_MIN_SCORE:
            phrases.append(phrase)
    return phrases


def technical_score(words, phrases):
    """Returns the score 0-10."""
    if not words:
        return 5.0
    if not phrases:
        return 0.0

    term_words = set()
    for phrase in phrases:
        for word in phrase.split():
            if len(word) > 3:
                term_words.add(word.lower())

    count = 0
    for word in words:
        if word in term_words:
            count += 1
    density = count / len(words)
    return round(min(10.0, (density / 0.20) * 10.0), 2)


# ---------------------------------------------------------------
# Score 4: Gemini's opinion
# ---------------------------------------------------------------
def llm_score(opening_text, api_key):
    """Ask Gemini twice and average. Returns None if Gemini is not available."""
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

    scores = []
    for attempt in range(2):
        try:
            answer = generate_text(prompt, api_key, temperature=0.0)
        except Exception as error:
            print("[LLM] call failed:", error)
            break
        match = re.search(r"\b(\d+)\b", answer)
        if match:
            scores.append(max(1, min(10, int(match.group(1)))))

    if not scores:
        return None
    return round(sum(scores) / len(scores))


def find_opening_text(full_text):
    """The abstract up to the end of the introduction (or the first 3000 letters)."""
    abstract = re.search(r"\bAbstract\b", full_text, re.IGNORECASE)
    intro = re.search(r"\b(1\.?\s*)?Introduction\b", full_text, re.IGNORECASE)

    intro_end = None
    if intro:
        next_section = NEXT_SECTION.search(full_text, intro.end())
        if next_section:
            intro_end = next_section.start()
        else:
            intro_end = intro.end() + 2000

    if abstract and intro:
        return full_text[abstract.start():intro_end].strip()
    if abstract:
        return full_text[abstract.start():abstract.start() + 2000].strip()
    if intro:
        return full_text[intro.start():intro_end].strip()
    return full_text[:3000].strip()


# ---------------------------------------------------------------
# Put everything together
# ---------------------------------------------------------------
def analyze_difficulty(full_text, api_key):
    words = get_content_words(full_text)

    uncommon_words = []
    for word in words:
        if word_frequency(word, "en") < RARE_WORD_LIMIT:
            uncommon_words.append(word)

    r_score, grade, ease = readability_score(full_text)
    phrases = find_keyphrases(full_text)
    t_score = technical_score(words, phrases)

    technical_words = set()
    for phrase in phrases:
        for word in phrase.split():
            technical_words.add(word.lower())
    u_score = uncommon_score(words, uncommon_words, technical_words)

    l_score = llm_score(find_opening_text(full_text), api_key)
    if l_score is None:
        l_score = round((r_score + u_score + t_score) / 3, 1)     # Gemini failed: make a guess

    scores = {"readability": r_score, "uncommon_words": u_score,
              "technical_terms": t_score, "llm_perception": l_score}
    final = 0
    for name in WEIGHTS:
        final += scores[name] * WEIGHTS[name]
    final = round(final, 2)

    return {
        "scores": scores,
        "weights": WEIGHTS,
        "final_score": final,
        "difficulty_label": difficulty_label(final),
        "breakdown": {
            "total_sentences": len(sent_tokenize(full_text)),
            "total_words": len(words),
            "uncommon_word_pct": round(len(uncommon_words) / max(len(words), 1) * 100, 1),
            "technical_keyphrases": len(phrases),
            "technical_terms_list": phrases,
            "flesch_kincaid_grade": grade,
            "flesch_reading_ease": ease,
        },
    }