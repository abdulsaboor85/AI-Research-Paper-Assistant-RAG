"""Personalization: what the user already knows lowers difficulty + hides prerequisites."""

import copy
import re

DIFFICULTY_LABELS = [(3.5, "Easy"), (6.5, "Medium"), (10.0, "Hard")]

# Knowing ALL prerequisites can lower the LLM score by at most this much (50%).
MAX_LLM_REDUCTION = 0.5

# Words that don't change which concept a phrase is about.
GENERIC_WORDS = {
    "mechanism", "function", "architecture", "model", "network", "layer",
    "method", "technique", "concept", "basic", "algorithm", "process",
    "and", "of", "the", "for", "in", "to", "a", "on", "with",
}

PREREQ_LINE = re.compile(r"^\s*\d+[.)]\s*(.+)")


def difficulty_label(score: float) -> str:
    for threshold, label in DIFFICULTY_LABELS:
        if score <= threshold:
            return label
    return "Very Hard"


def _core_tokens(text: str) -> set[str]:
    """Lowercase words, plural -> singular, generic words removed."""
    tokens = set()
    for word in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        if word not in GENERIC_WORDS:
            tokens.add(word)
    return tokens


def terms_match(known: str, candidate: str, loose: bool = False) -> bool:
    """
    True if the user's known term means the same concept as `candidate`.
      strict (prerequisites): same core words, or the smaller phrase has 2+ words
                              and sits fully inside the bigger one.
      loose  (KeyBERT terms): any containment counts.
    """
    k, c = _core_tokens(known), _core_tokens(candidate)
    if not k or not c:
        return False
    if k == c:
        return True
    small, big = (k, c) if len(k) <= len(c) else (c, k)
    return small <= big and (loose or len(small) >= 2)


def prereq_topic(line_text: str) -> str:
    """'Softmax Function: Mathematical tool...' -> 'Softmax Function'"""
    return line_text.split(":")[0].strip()


def parse_prereq_topics(prereq_text: str | None) -> list[str]:
    topics = []
    for line in (prereq_text or "").split("\n"):
        match = PREREQ_LINE.match(line)
        if match:
            topics.append(prereq_topic(match.group(1)))
    return topics


def personalize_analysis(base_result: dict, known_terms: set[str],
                         base_prereq_text: str | None = None) -> dict:
    """Returns a COPY of the base analysis, lowered for what this user knows."""
    result = copy.deepcopy(base_result)
    if not known_terms:
        return result

    scores, weights = result["scores"], result["weights"]

    tech_terms = result.get("breakdown", {}).get("technical_terms_list") or []
    tech_matched = sum(
        1 for term in tech_terms if any(terms_match(k, term, loose=True) for k in known_terms)
    )

    prereqs = parse_prereq_topics(base_prereq_text)
    prereq_matched = sum(1 for t in prereqs if any(terms_match(k, t) for k in known_terms))

    if not tech_matched and not prereq_matched:
        return result

    if tech_matched:
        scores["technical_terms"] = round(
            scores["technical_terms"] * (1 - tech_matched / len(tech_terms)), 2
        )
    if prereq_matched:
        cut = MAX_LLM_REDUCTION * prereq_matched / len(prereqs)
        scores["llm_perception"] = round(scores["llm_perception"] * (1 - cut), 2)

    final = round(sum(scores[key] * weights[key] for key in weights), 2)

    result["final_score"] = final
    result["difficulty_label"] = difficulty_label(final)
    result["personalization"] = {
        "known_terms_matched": tech_matched,
        "total_technical_terms": len(tech_terms),
        "prereqs_known": prereq_matched,
        "total_prereqs": len(prereqs),
        "base_final_score": base_result["final_score"],
    }
    return result


def personalize_prerequisites(base_text: str, known_terms: set[str]) -> str:
    """Remove prerequisites the user already knows, then renumber the list."""
    if not base_text or not known_terms:
        return base_text

    lines, number = [], 0
    for line in base_text.strip().split("\n"):
        match = PREREQ_LINE.match(line)
        if not match:
            lines.append(line)
            continue
        if any(terms_match(k, prereq_topic(match.group(1))) for k in known_terms):
            continue
        number += 1
        lines.append(f"{number}. {match.group(1)}")
    return "\n".join(lines)