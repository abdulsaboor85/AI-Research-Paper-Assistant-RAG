"""
personalization.py  -  make results fit the user, using their Memory (learned terms).

HOW THIS FILE WORKS (easy words)
------------------------------------------------------------
When you explain a term, the app saves it as "learned". After that:
  * The learning roadmap HIDES topics you already know.
  * The difficulty score gets LOWER (the paper is easier for you).
To know if two phrases mean the same idea, we compare their important words.
   "attention"  and  "Attention Mechanism"   -> same idea
We always work on a COPY, so the saved original result is never changed.

FUNCTION GUIDE
------------------------------------------------------------
   difficulty_label        turn a score into Easy / Medium / Hard
   core_words              the important words of a phrase (no filler words)
   terms_match             do two phrases mean the same idea?
   parse_prereq_topics     get the topic names out of the numbered roadmap text
   count_matches           how many items match a known term
   personalize_analysis    lower the difficulty score for what the user knows
   personalize_prerequisites   remove the roadmap topics the user already knows
"""

import copy
import re

DIFFICULTY_LABELS = [(3.5, "Easy"), (6.5, "Medium"), (10.0, "Hard")]

# Knowing ALL prerequisites can lower the AI score by at most 50%
MAX_LLM_REDUCTION = 0.5

# Words that do not change what a phrase is about
FILLER_WORDS = {
    "mechanism", "function", "architecture", "model", "network", "layer",
    "method", "technique", "concept", "basic", "algorithm", "process",
    "and", "of", "the", "for", "in", "to", "a", "on", "with",
}

# A roadmap line looks like:  3. Topic: explanation
PREREQ_LINE = re.compile(r"^\s*\d+[.)]\s*(.+)")


def difficulty_label(score):
    for highest, label in DIFFICULTY_LABELS:
        if score <= highest:
            return label
    return "Very Hard"


def core_words(text):
    """The lowercase words of a phrase. Plural 's' removed, filler words dropped."""
    words = set()
    for word in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        if word not in FILLER_WORDS:
            words.add(word)
    return words


def terms_match(known, candidate, loose=False):
    """True if the known term means the same idea as the candidate.
    strict (loose=False): same words, or the smaller phrase has 2+ words and sits inside the bigger one.
    loose  (loose=True):  any phrase that sits inside the other counts."""
    known_words = core_words(known)
    candidate_words = core_words(candidate)
    if not known_words or not candidate_words:
        return False
    if known_words == candidate_words:
        return True

    if len(known_words) <= len(candidate_words):
        small = known_words
        big = candidate_words
    else:
        small = candidate_words
        big = known_words

    if not small.issubset(big):
        return False
    return loose or len(small) >= 2


def parse_prereq_topics(prereq_text):
    """The topic names from the numbered list (the text before the colon)."""
    topics = []
    for line in (prereq_text or "").split("\n"):
        match = PREREQ_LINE.match(line)
        if match:
            topics.append(match.group(1).split(":")[0].strip())
    return topics


def count_matches(known_terms, items, loose=False):
    """How many of the items match at least one known term."""
    total = 0
    for item in items:
        for known in known_terms:
            if terms_match(known, item, loose):
                total += 1
                break
    return total


def personalize_analysis(base_result, known_terms, prereq_text=None):
    """Return a COPY of the analysis, made easier for what this user knows:
         technical_terms goes down by the share of keyphrases the user knows
         llm_perception goes down (at most 50%) by the share of prerequisites known"""
    result = copy.deepcopy(base_result)
    if not known_terms:
        return result

    keyphrases = result.get("breakdown", {}).get("technical_terms_list") or []
    prereqs = parse_prereq_topics(prereq_text)
    tech_matched = count_matches(known_terms, keyphrases, loose=True)
    prereq_matched = count_matches(known_terms, prereqs)
    if tech_matched == 0 and prereq_matched == 0:
        return result

    scores = result["scores"]
    weights = result["weights"]
    base_final = result["final_score"]

    if tech_matched:
        scores["technical_terms"] = round(scores["technical_terms"] * (1 - tech_matched / len(keyphrases)), 2)
    if prereq_matched:
        reduction = MAX_LLM_REDUCTION * prereq_matched / len(prereqs)
        scores["llm_perception"] = round(scores["llm_perception"] * (1 - reduction), 2)

    final = 0
    for name in weights:
        final += scores[name] * weights[name]
    final = round(final, 2)

    result["final_score"] = final
    result["difficulty_label"] = difficulty_label(final)
    result["personalization"] = {
        "known_terms_matched": tech_matched,
        "total_technical_terms": len(keyphrases),
        "prereqs_known": prereq_matched,
        "total_prereqs": len(prereqs),
        "base_final_score": base_final,
    }
    return result


def personalize_prerequisites(base_text, known_terms):
    """Remove the topics the user already knows, then number the rest again."""
    if not base_text or not known_terms:
        return base_text

    kept_lines = []
    number = 1
    for line in base_text.strip().split("\n"):
        match = PREREQ_LINE.match(line)
        if not match:
            kept_lines.append(line)
            continue

        topic = match.group(1).split(":")[0].strip()
        already_known = False
        for known in known_terms:
            if terms_match(known, topic):
                already_known = True
                break
        if already_known:
            continue

        kept_lines.append(str(number) + ". " + match.group(1))
        number += 1
    return "\n".join(kept_lines)