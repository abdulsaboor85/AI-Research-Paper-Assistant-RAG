"""
comparer.py  -  compare 2 or 3 papers side by side.

HOW THIS FILE WORKS (easy words)
------------------------------------------------------------
Think of a teacher who puts the notes of 2 or 3 students next to each other.
1. app.py gives us one "bundle" for each paper. A bundle is a dictionary with
   everything we ALREADY know about that paper:
      name, title, path, summary, analysis (difficulty), prereqs (text or None),
      pages, read_minutes
2. The CONCEPTS of a paper are its prerequisite topics (clean, real topics).
   Only if a paper has no prerequisite list, we use its key phrases as a backup.
3. relatedness():  are the papers about the same topic?
      60% = how close their meaning is (embedding numbers)
      40% = how many concepts they share
   Related (60% or more), Somewhat related (30% or more), or Unrelated.
4. shared_and_unique():  concepts that 2+ papers have, and concepts only one paper has.
5. head_to_head():  the same metric (for example "BLEU score") measured in 2+ papers.
6. reading_order():  the easiest paper first. (The page may swap two papers with
   almost the same score, using the AI verdict "read_first".)
7. build_comparison():  puts all of this in ONE dictionary for the browser.
8. build_verdict():  asks Gemini ONE time for a short opinion. app.py saves it.
This file has no Flask and does not touch the disk. app.py does that.

FUNCTION GUIDE
------------------------------------------------------------
 SMALL HELPERS
   text_of               any value -> clean text
   is_stated             is this a real answer (not "Not stated")?
   get_section           short + detailed text of one summary card
   first_number          the first number found in a text
   contains_concept      does a concept match any concept in a list?
 CONCEPTS
   get_keyphrases        key phrases saved in the difficulty result (backup only)
   get_concepts          the prerequisite topics of one paper
   concept_overlap       how much two concept lists overlap
 RELATEDNESS
   embed_summaries       turn each paper's summary into numbers
   pair_relatedness      relatedness of ONE pair of papers
   level_for             score -> related / somewhat / unrelated
   relatedness           relatedness of all the papers
 SHARED AND UNIQUE CONCEPTS
   concepts_of_others    the concepts of all papers except one
   find_shared_concepts  concepts that appear in 2+ papers
   find_unique_concepts  concepts that only one paper has
   shared_and_unique     both lists together
 DIFFICULTY
   pack_difficulty       score, label and 4 parts of one analysis
   difficulty_for        standard and personalized difficulty of one paper
 HEAD TO HEAD
   higher_is_better      is a bigger number better for this metric?
   metric_key            clean metric name, to match across papers
   collect_metric_slots  group the numbers by metric
   pick_winner           the paper with the best number (or None)
   head_to_head          same metric measured in several papers
 READING ORDER
   reading_reason        one sentence: why this paper is at this place
   reading_order         which paper to read first, second...
 MAIN
   count_prerequisites   how many prerequisites a paper has, and how many are left
   key_numbers_of        the key numbers of a summary
   paper_info            everything the browser shows for ONE paper
   build_comparison      the full comparison result
 AI VERDICT
   comparison_key        short name of a group of papers (for saving)
   paper_block           the text about one paper for Gemini
   verdict_prompt        the full instruction for Gemini
   parse_json            find the JSON inside Gemini's answer
   clean_best_for        keep only valid "best for" entries
   build_verdict         ask Gemini for the verdict
"""

import hashlib
import json
import re

from model_config import generate_text
from personalization import (difficulty_label, parse_prereq_topics, personalize_analysis,
                             personalize_prerequisites, terms_match)

MIN_PAPERS = 2
MAX_PAPERS = 3          # to allow 4, change this AND CMP_MAX in index.html
NOT_STATED = "Not stated in the paper."
LETTERS = "ABCD"

COMPONENTS = ["readability", "uncommon_words", "technical_terms", "llm_perception"]
SECTION_KEYS = ["about", "problem", "did", "results", "limits"]

# Relatedness settings
SIM_LOW = 0.45               # meaning similarity at or below this counts as 0
SIM_HIGH = 0.80              # meaning similarity at or above this counts as 1
WEIGHT_SIMILARITY = 0.6
WEIGHT_TERMS = 0.4
RELATED_AT = 0.60            # this score or more = "related"
SOMEWHAT_AT = 0.30           # this score or more = "somewhat", less = "unrelated"
MAX_CONCEPTS = 120

# Change this text when you change the verdict instruction.
# Old saved verdicts are then made again by themselves.
VERDICT_VERSION = "v2"

LEVELS = {
    "related": ("Related",
                "These papers cover the same topic, so a full comparison is meaningful."),
    "somewhat": ("Somewhat related",
                 "These papers overlap a little. Compare the shared parts and treat the rest as separate topics."),
    "unrelated": ("Unrelated",
                  "These papers cover different topics, so there is no direct comparison. "
                  "Here is a side-by-side overview instead."),
}


# ---------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------
def text_of(value):
    if not value:
        return ""
    return str(value).strip()


def is_stated(text):
    return bool(text) and text != NOT_STATED


def get_section(summary, key):
    """The {"short": ..., "detailed": ...} text of one summary card."""
    item = {}
    if summary:
        item = summary.get(key)
    if not isinstance(item, dict):
        item = {}
    short = text_of(item.get("short"))
    detailed = text_of(item.get("detailed"))
    return {"short": short or detailed or NOT_STATED,
            "detailed": detailed or short or NOT_STATED}


def first_number(value):
    """The first number inside a text as a float, or None."""
    match = re.search(r"-?\d+(?:\.\d+)?", text_of(value).replace(",", ""))
    if match:
        return float(match.group())
    return None


def contains_concept(concept, candidates):
    """True if the concept means the same idea as ANY of the candidates."""
    for candidate in candidates:
        if terms_match(concept, candidate, loose=True):
            return True
    return False


# ---------------------------------------------------------------
# Concepts
# ---------------------------------------------------------------
def get_keyphrases(analysis):
    """The key phrases saved in the difficulty result (we use them only as a backup)."""
    breakdown = {}
    if analysis:
        breakdown = analysis.get("breakdown") or {}

    phrases = []
    for item in breakdown.get("technical_terms_list") or []:
        phrase = text_of(item)
        if phrase:
            phrases.append(phrase)
    return phrases


def get_concepts(bundle):
    """The concepts of one paper = its prerequisite topics (clean and real).
    Only if the paper has no prerequisite list, we use the key phrases instead."""
    topics = parse_prereq_topics(bundle.get("prereqs"))
    if len(topics) == 0:
        topics = get_keyphrases(bundle.get("analysis"))

    seen = set()
    concepts = []
    for phrase in topics:
        key = phrase.lower()
        if key not in seen:
            seen.add(key)
            concepts.append(phrase)
    return concepts[:MAX_CONCEPTS]


def concept_overlap(mine, other):
    """Returns (overlap from 0 to 1, my concepts that also appear in "other")."""
    if not mine or not other:
        return 0.0, []

    shared = []
    for concept in mine:
        if contains_concept(concept, other):
            shared.append(concept)

    smaller_size = min(len(mine), len(other))
    score = min(1.0, len(shared) / max(1.0, 0.25 * smaller_size))
    return score, shared


# ---------------------------------------------------------------
# Relatedness
# ---------------------------------------------------------------
def embed_summaries(bundles):
    """Turn each paper's "about + problem" text into numbers. None if that is not possible."""
    texts = []
    for bundle in bundles:
        parts = []
        for key in ["about", "problem"]:
            part = get_section(bundle.get("summary"), key)["short"]
            if is_stated(part):
                parts.append(part)
        texts.append(" ".join(parts))

    for text in texts:
        if not text:
            return None

    try:
        from embedder import model          # the same model the rest of the app uses
        return model.encode(texts, convert_to_numpy=True,
                            normalize_embeddings=True, show_progress_bar=False)
    except Exception as error:
        print("[comparer] embedding skipped:", error)
        return None


def pair_relatedness(i, j, concepts, vectors):
    """How related are paper i and paper j? Mixes meaning and shared concepts."""
    overlap, shared = concept_overlap(concepts[i], concepts[j])
    score = overlap
    similarity = None

    if vectors is not None:
        # the vectors are normalized, so "dot" gives the cosine similarity (-1 to 1)
        cosine = float(vectors[i].dot(vectors[j]))
        similarity = max(0.0, min(1.0, (cosine - SIM_LOW) / (SIM_HIGH - SIM_LOW)))
        score = WEIGHT_SIMILARITY * similarity + WEIGHT_TERMS * overlap
        similarity = round(similarity, 3)

    return {"a": i, "b": j, "score": round(score, 3), "percent": round(score * 100),
            "shared_n": len(shared), "similarity": similarity}


def level_for(score):
    if score >= RELATED_AT:
        return "related"
    if score >= SOMEWHAT_AT:
        return "somewhat"
    return "unrelated"


def relatedness(bundles):
    """How related are all the papers? The average of all pairs."""
    concepts = []
    for bundle in bundles:
        concepts.append(get_concepts(bundle))
    vectors = embed_summaries(bundles)

    pairs = []
    for i in range(len(bundles)):
        for j in range(i + 1, len(bundles)):
            pairs.append(pair_relatedness(i, j, concepts, vectors))

    total = 0.0
    for pair in pairs:
        total += pair["score"]
    overall = 0.0
    if pairs:
        overall = total / len(pairs)

    level = level_for(overall)
    label, message = LEVELS[level]
    return {"score": round(overall, 3), "percent": round(overall * 100), "level": level,
            "label": label, "message": message, "pairs": pairs}


# ---------------------------------------------------------------
# Shared and unique concepts
# ---------------------------------------------------------------
def concepts_of_others(all_concepts, i):
    """The concepts of all papers EXCEPT paper number i."""
    others = []
    for j in range(len(all_concepts)):
        if j != i:
            others = others + all_concepts[j]
    return others


def find_shared_concepts(all_concepts, known_terms):
    """Concepts that appear in at least 2 papers. "known" = the user already learned it."""
    shared = []
    shared_terms = []
    for i in range(len(all_concepts)):
        others = concepts_of_others(all_concepts, i)
        for concept in all_concepts[i]:
            if contains_concept(concept, shared_terms):
                continue                      # already in the list
            if contains_concept(concept, others):
                shared_terms.append(concept)
                shared.append({"term": concept, "known": contains_concept(concept, known_terms)})
    return shared[:12]


def find_unique_concepts(all_concepts):
    """For each paper: the concepts that no other paper has."""
    unique = []
    for i in range(len(all_concepts)):
        others = concepts_of_others(all_concepts, i)
        only_here = []
        for concept in all_concepts[i]:
            if not contains_concept(concept, others):
                only_here.append(concept)
        unique.append(only_here[:8])
    return unique


def shared_and_unique(bundles, known_terms):
    all_concepts = []
    for bundle in bundles:
        all_concepts.append(get_concepts(bundle)[:60])
    return {"shared": find_shared_concepts(all_concepts, known_terms),
            "unique": find_unique_concepts(all_concepts)}


# ---------------------------------------------------------------
# Difficulty (standard and personalized)
# ---------------------------------------------------------------
def pack_difficulty(analysis):
    score = float(analysis.get("final_score") or 0)
    scores = analysis.get("scores") or {}

    components = {}
    for name in COMPONENTS:
        components[name] = round(float(scores.get(name) or 0), 1)

    return {"score": round(score, 1),
            "label": analysis.get("difficulty_label") or difficulty_label(score),
            "components": components}


def difficulty_for(bundle, known_terms):
    """Returns (standard difficulty, personalized difficulty, personalization info)."""
    base = bundle.get("analysis") or {}
    personalized = personalize_analysis(base, known_terms, bundle.get("prereqs"))
    return pack_difficulty(base), pack_difficulty(personalized), personalized.get("personalization")


# ---------------------------------------------------------------
# Head to head (the same metric in several papers)
# ---------------------------------------------------------------
def higher_is_better(comparison):
    """True or False if the summary tells us, else None."""
    if comparison.get("good") is True:
        return comparison.get("direction") == "up"
    if comparison.get("good") is False:
        return comparison.get("direction") == "down"
    return None


def metric_key(name):
    """"Word Error Rate!" -> "word error rate" (to match the same metric in different papers)."""
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def collect_metric_slots(bundles):
    """Group the numbers by metric. slots[metric key] = the numbers of each paper."""
    slots = {}
    for index in range(len(bundles)):
        summary = bundles[index].get("summary") or {}
        for comparison in summary.get("comparisons") or []:
            key = metric_key(text_of(comparison.get("metric")))
            number = first_number(comparison.get("new"))
            if not key or number is None:
                continue

            if key not in slots:
                slots[key] = {"metric": text_of(comparison.get("metric")),
                              "unit": text_of(comparison.get("unit")),
                              "better_is_higher": None, "values": {}}
            slot = slots[key]
            if slot["better_is_higher"] is None:
                slot["better_is_higher"] = higher_is_better(comparison)
            if index not in slot["values"]:
                slot["values"][index] = {"index": index, "value": text_of(comparison.get("new")),
                                         "num": number, "label": text_of(comparison.get("new_label"))}
    return slots


def pick_winner(values, better_is_higher):
    """The index of the paper with the best number. None if we cannot tell or it is a tie."""
    if better_is_higher is None:
        return None

    numbers = []
    for value in values:
        numbers.append(value["num"])
    if better_is_higher:
        best = max(numbers)
    else:
        best = min(numbers)

    winners = []
    for value in values:
        if value["num"] == best:
            winners.append(value["index"])
    if len(winners) == 1:
        return winners[0]
    return None


def head_to_head(bundles):
    """Metrics that at least 2 papers report, and who is best on each."""
    slots = collect_metric_slots(bundles)

    rows = []
    for key in slots:
        slot = slots[key]
        if len(slot["values"]) < 2:
            continue

        values = []
        for index in range(len(bundles)):
            if index in slot["values"]:
                values.append(slot["values"][index])

        rows.append({"metric": slot["metric"], "unit": slot["unit"], "values": values,
                     "winner": pick_winner(values, slot["better_is_higher"]),
                     "higher_is_better": slot["better_is_higher"]})
    return {"rows": rows[:6]}


# ---------------------------------------------------------------
# Reading order
# ---------------------------------------------------------------
def reading_reason(position, i, order, scores, concepts, level):
    """One sentence that says why paper i is at this place in the reading order."""
    if position == 0:
        return "Start here. It has the lowest difficulty (" + ("%.1f" % scores[i]) + " / 10)."
    if level == "unrelated":
        return "Different topic, so it is ordered by difficulty only."

    earlier_concepts = []
    for j in order[:position]:
        earlier_concepts = earlier_concepts + concepts[j]
    overlap, shared = concept_overlap(concepts[i], earlier_concepts)
    if len(shared) >= 3:
        return "Builds on " + ", ".join(shared[:2]) + ", which the earlier paper(s) cover."
    return "Harder (" + ("%.1f" % scores[i]) + " / 10), so read it after the easier one(s)."


def reading_order(scores, prereqs_left, concepts, level):
    """Easiest paper first. If the scores are equal, fewer prerequisites left comes first."""
    sortable = []
    for i in range(len(scores)):
        left = prereqs_left[i]
        if left is None:
            left = 99
        sortable.append((scores[i], left, i))
    sortable.sort()

    order = []
    for item in sortable:
        order.append(item[2])

    steps = []
    for position in range(len(order)):
        i = order[position]
        steps.append({"index": i, "reason": reading_reason(position, i, order, scores, concepts, level)})
    return steps


# ---------------------------------------------------------------
# Main comparison
# ---------------------------------------------------------------
def count_prerequisites(prereq_text, known_terms):
    """Returns (how many prerequisites, how many are left for this user). (None, None) if no list."""
    if not prereq_text:
        return None, None
    total = len(parse_prereq_topics(prereq_text))
    left = len(parse_prereq_topics(personalize_prerequisites(prereq_text, known_terms)))
    return total, left


def key_numbers_of(summary):
    numbers = []
    for item in summary.get("key_numbers") or []:
        if isinstance(item, dict):
            numbers.append({"value": text_of(item.get("value")), "label": text_of(item.get("label"))})
    return numbers[:4]


def paper_info(index, bundle, known_terms):
    """Everything the browser shows for ONE paper."""
    base, personalized, info = difficulty_for(bundle, known_terms)
    total, left = count_prerequisites(bundle.get("prereqs"), known_terms)

    summary = bundle.get("summary") or {}
    sections = {}
    for key in SECTION_KEYS:
        sections[key] = get_section(summary, key)

    return {
        "index": index, "letter": LETTERS[index], "title": bundle["title"], "path": bundle["path"],
        "pages": bundle.get("pages"), "read_minutes": bundle.get("read_minutes"),
        "difficulty": {"base": base, "personalized": personalized},
        "personalization": info,
        "prereqs": {"total": total, "left": left},
        "sections": sections,
        "key_numbers": key_numbers_of(summary),
    }


def build_comparison(bundles, known_terms):
    """The full result that the Compare tab shows."""
    related = relatedness(bundles)

    papers = []
    concepts = []
    base_scores = []
    personalized_scores = []
    prereq_totals = []
    prereq_lefts = []
    for i in range(len(bundles)):
        paper = paper_info(i, bundles[i], known_terms)
        papers.append(paper)
        concepts.append(get_concepts(bundles[i]))
        base_scores.append(paper["difficulty"]["base"]["score"])
        personalized_scores.append(paper["difficulty"]["personalized"]["score"])
        prereq_totals.append(paper["prereqs"]["total"])
        prereq_lefts.append(paper["prereqs"]["left"])

    level = related["level"]
    return {
        "papers": papers,
        "relatedness": related,
        "concepts": shared_and_unique(bundles, known_terms),
        "head_to_head": head_to_head(bundles),
        "reading_order": {
            "base": reading_order(base_scores, prereq_totals, concepts, level),
            "personalized": reading_order(personalized_scores, prereq_lefts, concepts, level),
        },
        "has_personalization": base_scores != personalized_scores,
    }


# ---------------------------------------------------------------
# AI verdict (one Gemini call; app.py saves the answer)
# ---------------------------------------------------------------
def comparison_key(bundles, level):
    """A short name for this group of papers. It is the file name of the saved verdict."""
    names = []
    for bundle in bundles:
        names.append(bundle["name"])
    raw = "|".join(names) + "|" + level + "|" + VERDICT_VERSION
    return "cmp_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def paper_block(letter, bundle):
    """The short text about one paper that we give to Gemini."""
    summary = bundle.get("summary") or {}
    lines = ["PAPER " + letter + ": " + bundle["title"]]

    labels = [("about", "About"), ("problem", "Problem"), ("did", "Method"),
              ("results", "Results"), ("limits", "Limits")]
    for key, label in labels:
        lines.append("- " + label + ": " + get_section(summary, key)["short"])

    comparisons = summary.get("comparisons") or []
    for c in comparisons[:3]:
        lines.append("- Reported: " + text_of(c.get("metric")) + ": " + text_of(c.get("old_label")) + " " +
                     text_of(c.get("old")) + " -> " + text_of(c.get("new_label")) + " " +
                     text_of(c.get("new")) + " " + text_of(c.get("unit")))
    return "\n".join(lines)


def verdict_prompt(bundles, level):
    blocks = []
    for i in range(len(bundles)):
        blocks.append(paper_block(LETTERS[i], bundles[i]))
    all_blocks = "\n\n".join(blocks)
    label, message = LEVELS[level]

    return f"""You are an academic tutor helping a university student compare research papers.

=== PAPERS (summaries only) ===
{all_blocks}

=== HOW RELATED THEY ARE ===
{label}. {message}

=== OUTPUT ===
Return ONLY valid JSON, no markdown, in exactly this shape:
{{"verdict": "2-3 sentences", "relation": "1 sentence on how the papers relate",
  "best_for": [{{"paper": "A", "goal": "short goal this paper is best for"}}],
  "read_first": "A"}}

=== RULES ===
- Simple, clear English. Use ONLY the information above. Never invent numbers.
- If the papers are Unrelated, say plainly that they solve different problems. Do NOT pick an overall winner
  and do NOT invent similarities. Describe what each paper is good for instead.
- If they are Related, say which is stronger for what (accuracy, simplicity, speed, depth), based on the text.
- best_for has one entry per paper.
- read_first is the letter of the paper a student should read FIRST.
  If one paper builds on another (it uses the other paper's idea), choose the BASE paper (the one it builds on).
  Otherwise choose the paper that is easier to understand.
- No markdown symbols inside the text."""


def parse_json(raw_answer):
    """Gemini sometimes adds ```json fences. Cut them away and read the JSON."""
    raw_answer = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_answer.strip())
    start = raw_answer.find("{")
    end = raw_answer.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON found in the reply.")
    return json.loads(raw_answer[start:end + 1], strict=False)


def clean_best_for(data, valid_letters):
    """Keep only entries with a real paper letter and a goal text."""
    items = data.get("best_for")
    if not isinstance(items, list):
        items = []

    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        letter = text_of(item.get("paper")).upper()
        goal = text_of(item.get("goal"))
        if letter in valid_letters and goal:
            result.append({"paper": letter, "goal": goal})
    return result[:len(valid_letters)]


def build_verdict(bundles, level, api_key):
    raw = generate_text(verdict_prompt(bundles, level), api_key, temperature=0.2,
                        max_output_tokens=1200, response_mime_type="application/json")
    valid_letters = LETTERS[:len(bundles)]

    try:
        data = parse_json(raw)
    except ValueError:
        # Gemini did not send JSON: show its text as the verdict
        return {"verdict": text_of(raw)[:700], "relation": "", "best_for": [], "read_first": ""}

    read_first = text_of(data.get("read_first")).upper()
    if read_first not in valid_letters:
        read_first = ""

    return {"verdict": text_of(data.get("verdict")), "relation": text_of(data.get("relation")),
            "best_for": clean_best_for(data, valid_letters), "read_first": read_first}