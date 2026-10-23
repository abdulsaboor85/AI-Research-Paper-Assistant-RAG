"""
summarizer.py  -  write the summary of a paper (5 cards + numbers).

HOW THIS FILE WORKS (easy words)
------------------------------------------------------------
We do NOT send the whole paper to Gemini any more. We send only the important parts.
1. Cut off the reference list.
2. SAFETY 1: if the paper is short, send the full text (nothing is lost).
3. LAYER 1: look for the headings of 5 parts:
      Abstract, Introduction, Method, Results, Conclusion
   and copy the text under each heading.
4. LAYER 2: if a part is missing, ask ChromaDB (free, no Gemini), like the Q&A:
      "What are the results of this paper?"  and take the chunks it gives.
5. Put all the parts together.
6. SAFETY 2: if we found almost nothing, use the OLD way (the whole paper, trimmed).
7. Ask Gemini ONE time to answer in JSON (a computer-friendly format) with:
     5 cards: about, problem, did, results, limits  (each has a "short" and a "detailed" text)
     comparisons: old method vs new method on the same metric
     key_numbers: other important result numbers (each has a value, a unit and a label)
8. CHECK Gemini's work. This is the important part:
     * Every number must really appear in the PDF text, or we drop it.
     * If a number has no unit, we look in the paper for a % sign next to it.
     * WE do the maths (difference, percent, bar widths), not Gemini.
9. If the JSON is broken, we try one more time.

FUNCTION GUIDE
------------------------------------------------------------
 CUTTING THE TEXT
   cut_references        cut the reference list
   prepare_text          OLD way: cut references and trim a very long text
 LAYER 1: FIND PARTS BY HEADING
   clean_heading         a line in small letters, without its number
   is_any_heading        is this line a heading we know?
   is_top_heading        is this line a main heading (it ends a part)?
   find_heading_lines    where does each part start?
   find_section_end      where does a part end?
   find_sections         the text of each part we can find
 LAYER 2: SEARCH WITH CHROMADB
   search_missing_part   ask ChromaDB for the chunks of a missing part
   collect_parts         layer 1 + layer 2, put all parts together
   pick_text             choose what to send to Gemini (with the safety rules)
 ASK GEMINI AND CHECK
   build_prompt          the instruction we send to Gemini
   parse_json            turn Gemini's answer into a Python dictionary
   to_text               turn any value into clean text
   find_number           find the first number inside a text
   number_in_paper       is this number written in the paper?
   guess_unit            look in the paper: is this number a percent?
   join_value_and_unit   "94" + "%" -> "94%"
   format_change         "+2.1" style text for a difference
   bar_widths            how long the two bars should be (0-100)
   clean_comparisons     check and finish the comparison rows
   clean_key_numbers     check the key numbers and add their unit
   clean_card            make sure a card has "short" and "detailed" text
   clean_summary         clean everything Gemini returned
   summarize_paper       the main function
"""

import json
import re

from embedder import collection_exists_and_has_data
from extractor import MIN_TEXT_LENGTH, extract_text
from model_config import generate_text
from retriever import retrieve_relevant_chunks

NOT_STATED = "Not stated in the paper."
MAX_CHARS = 60000                      # the OLD way: a longer paper is trimmed to this
CARD_NAMES = ["about", "problem", "did", "results", "limits"]

# ---------------------------------------------------------------
# Settings for the "important parts" plan
# ---------------------------------------------------------------
SHORT_PAPER_CHARS = 16000     # a paper this short (about 4000 tokens) is sent in full
MIN_SECTION_CHARS = 300       # a part with less text than this counts as "missing"
MIN_TOTAL_CHARS = 1500        # if all parts together are shorter, use the old way

PART_ORDER = ["abstract", "introduction", "method", "results", "conclusion"]

PART_TITLES = {
    "abstract": "ABSTRACT",
    "introduction": "INTRODUCTION",
    "method": "METHOD",
    "results": "RESULTS",
    "conclusion": "CONCLUSION",
}

# The headings we look for (small letters, no numbers)
HEADING_NAMES = {
    "abstract": ["abstract"],
    "introduction": ["introduction"],
    "method": ["method", "methods", "methodology", "approach", "proposed method",
               "proposed approach", "our approach", "model architecture", "proposed model",
               "materials and methods", "system architecture", "proposed system",
               "framework", "proposed framework"],
    "results": ["results", "experiments", "experimental results", "results and discussion",
                "evaluation", "experiments and results", "discussion"],
    "conclusion": ["conclusion", "conclusions", "conclusion and future work",
                   "conclusions and future work", "discussion and conclusion",
                   "future work", "concluding remarks"],
}

# Headings that always end a part
END_HEADINGS = ["references", "acknowledgments", "acknowledgements", "bibliography", "appendix"]

# The most letters we keep for each part (about 4000 tokens in total)
MAX_PART_CHARS = {
    "abstract": 2000,
    "introduction": 3500,
    "method": 4000,
    "results": 5000,
    "conclusion": 2500,
}

# The question we ask ChromaDB when a part is missing
SEARCH_QUESTIONS = {
    "abstract": "What is this paper about?",
    "introduction": "What problem does this paper try to solve and why does it matter?",
    "method": "What method or approach do the authors use?",
    "results": "What are the results of this paper?",
    "conclusion": "What are the conclusion, limitations and future work of this paper?",
}

# The shape of the answer we ask Gemini for
SCHEMA = """{
  "about":   {"short": "...", "detailed": "..."},
  "problem": {"short": "...", "detailed": "..."},
  "did":     {"short": "...", "detailed": "..."},
  "results": {"short": "...", "detailed": "..."},
  "limits":  {"short": "...", "detailed": "..."},
  "comparisons": [
    {"metric": "Accuracy", "old_label": "Old model", "old": "20", "new_label": "New model",
     "new": "80", "unit": "%", "higher_is_better": true}
  ],
  "key_numbers": [
    {"value": "94.2", "unit": "%", "label": "Accuracy of the proposed model on the test set"}
  ]
}"""


# ---------------------------------------------------------------
# Cutting the text
# ---------------------------------------------------------------
def cut_references(full_text):
    """Cut the reference list (only if it is in the second half of the paper)."""
    text = full_text.strip()
    matches = list(re.finditer(r"\n\s*(references|bibliography)\s*\n", text, re.IGNORECASE))
    if matches and matches[-1].start() > len(text) * 0.5:
        text = text[:matches[-1].start()]
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def prepare_text(full_text):
    """The OLD way: cut the references. Keep only the start and the end of a very long paper."""
    text = cut_references(full_text)

    if len(text) > MAX_CHARS:
        head = text[:int(MAX_CHARS * 0.7)]
        tail = text[-int(MAX_CHARS * 0.3):]
        text = head + "\n\n[... middle of the paper trimmed ...]\n\n" + tail
    return text


# ---------------------------------------------------------------
# LAYER 1: find the parts by their headings
# ---------------------------------------------------------------
def clean_heading(line):
    """"3.1 Model Architecture:" -> "model architecture" (small letters, no number)."""
    text = line.strip().lower()
    text = re.sub(r"^(\d+(\.\d+)*\.?|[ivx]+\.)\s*", "", text)
    text = text.strip(" .:-")
    return text


def is_any_heading(line):
    """True if the line is one of the headings we look for (or a reference heading)."""
    cleaned = clean_heading(line)
    if cleaned == "":
        return False
    if cleaned in END_HEADINGS:
        return True
    for part in PART_ORDER:
        if cleaned in HEADING_NAMES[part]:
            return True
    return False


def is_top_heading(line):
    """True if the line is a MAIN heading like "4 Experiments" (it ends the part before it)."""
    text = line.strip()
    if len(text) < 4 or len(text) > 60:
        return False
    if re.match(r"^(\d{1,2}|[IVX]+)\.?\s+[A-Z][A-Za-z ,&:-]*$", text):
        return True
    return is_any_heading(text)


def find_heading_lines(lines):
    """For each part, the number of the line where its heading is (the first one we see)."""
    found = {}
    for number in range(len(lines)):
        cleaned = clean_heading(lines[number])
        if cleaned == "":
            continue

        for part in PART_ORDER:
            if part in found:
                continue
            if cleaned in HEADING_NAMES[part]:
                found[part] = number
            elif part == "abstract" and re.match(r"abstract\b", cleaned):
                found[part] = number      # for "Abstract - the text starts here"
    return found


def find_section_end(lines, start):
    """The line number where the part ends: the next main heading, or the end of the text."""
    for number in range(start + 1, len(lines)):
        if is_top_heading(lines[number]):
            return number
    return len(lines)


def find_sections(full_text):
    """LAYER 1. Returns a dictionary: part name -> text of that part (only the parts we found)."""
    lines = cut_references(full_text).split("\n")
    starts = find_heading_lines(lines)

    sections = {}
    for part in PART_ORDER:
        if part not in starts:
            continue
        start = starts[part]
        end = find_section_end(lines, start)
        text = "\n".join(lines[start:end]).strip()
        text = text[:MAX_PART_CHARS[part]]
        if len(text) >= MIN_SECTION_CHARS:
            sections[part] = text
    return sections


# ---------------------------------------------------------------
# LAYER 2: search with ChromaDB (free, no Gemini)
# ---------------------------------------------------------------
def search_missing_part(part, collection_name):
    """Ask ChromaDB a question about the part. Returns the best chunks joined as one text."""
    question = SEARCH_QUESTIONS[part]
    chunks = retrieve_relevant_chunks(question, collection_name=collection_name, top_k=6)
    text = "\n".join(chunks[:6])
    return text[:MAX_PART_CHARS[part]]


def collect_parts(full_text, collection_name):
    """Layer 1, then layer 2 for the missing parts. Returns all parts as ONE text."""
    sections = find_sections(full_text)

    missing = []
    for part in PART_ORDER:
        if part not in sections:
            missing.append(part)
    print("[summarizer] found by heading:", list(sections.keys()), "| missing:", missing)

    # layer 2 works only if the paper is already saved in ChromaDB (indexing is finished)
    if missing and collection_name and collection_exists_and_has_data(collection_name):
        for part in missing:
            try:
                text = search_missing_part(part, collection_name)
            except Exception as error:
                print("[summarizer] search failed for", part, ":", error)
                text = ""
            if text.strip():
                sections[part] = text
                print("[summarizer] found by search:", part)

    blocks = []
    for part in PART_ORDER:
        if part in sections:
            blocks.append("[" + PART_TITLES[part] + "]\n" + sections[part])
    return "\n\n".join(blocks)


def pick_text(full_text, collection_name):
    """Choose the text we send to Gemini. This is where the safety rules are."""
    body = cut_references(full_text)

    # SAFETY 1: a short paper is sent in full, so nothing is lost
    if len(body) <= SHORT_PAPER_CHARS:
        print("[summarizer] short paper: sending the full text")
        return prepare_text(full_text)

    important = collect_parts(full_text, collection_name)

    # SAFETY 2: we found almost nothing, so use the old way
    if len(important) < MIN_TOTAL_CHARS:
        print("[summarizer] not enough important parts: using the old way")
        return prepare_text(full_text)

    print("[summarizer] sending the important parts only:", len(important), "letters")
    return important


# ---------------------------------------------------------------
# Ask Gemini and check the answer
# ---------------------------------------------------------------
def build_prompt(text, title):
    return f"""You are an expert academic tutor. Summarize the research paper below for a university student.

Paper title: "{title}"

Note: the text below may hold only the most important parts of the paper (marked like [RESULTS]).

=== PAPER TEXT ===
{text}

=== OUTPUT ===
Return ONLY valid JSON, no markdown, no extra text, in exactly this shape:

{SCHEMA}

=== CARD MEANING ===
- about: what this paper is about and what kind of paper it is.
- problem: what problem the authors want to solve and why it matters.
- did: what the authors actually did (method, data, setup).
- results: what the paper found / concluded.
- limits: weaknesses the AUTHORS admit, plus the final conclusion and future work.

=== LENGTH ===
- "short": 1 to 2 simple sentences.
- "detailed": 4 to 6 SHORT points. Put each point on its own line (separate the points with a line break).
  Each point starts with a 1 to 3 word label and a colon, then ONE short sentence of at most 18 words.
  Example: "Idea: The model reads all the words at the same time."
  No long sentences. No paragraph.

=== COMPARISONS ===
- ONLY when the paper gives a number for an old/baseline method AND a number for the new/proposed method on the SAME metric.
- Max 3. Copy numbers EXACTLY as written, digits only (no % or unit inside the number).
- Put the unit in "unit" ("%", "ms", "s", ...). Use "" if there is no unit.
- higher_is_better: true for accuracy, F1, precision. false for error rate, latency, loss, WER.
- If the paper has no such pair, use an empty list [].

=== KEY NUMBERS ===
- Up to 4 important result numbers that are NOT already in comparisons.
- "value": the number as written, digits only (example: "94.2").
- "unit": ALWAYS fill it when the number has one: "%" for accuracy, rates and shares, or "ms", "s", "days", "GB"...
  Use "" ONLY when the number really has no unit (a plain count).
- "label": say CLEARLY what the number measures and for which system.
  Good: "Accuracy of the 1952 Bell Labs system".  Bad: "Accuracy" or "Number".
- If the paper gives a range like "94 to 99 percent", write TWO entries, each with its own unit and label
  (for example "Lowest accuracy of current systems" and "Highest accuracy of current systems").
- Only real results. Never page counts, years, or reference numbers.
- If none, use an empty list [].

=== STRICT RULES ===
- Write in simple, clear English, like explaining to a 15-year-old. If you use a technical word, explain it in brackets.
- Use ONLY the paper text above. Never add outside knowledge.
- Never invent numbers. If a card is not covered, write exactly "{NOT_STATED}" for both lengths.
- No markdown symbols (no **, no #) inside the text."""


def parse_json(raw_answer):
    """Turn Gemini's answer into a Python dictionary."""
    raw_answer = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_answer.strip())
    start = raw_answer.find("{")
    end = raw_answer.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON found in the reply.")
    return json.loads(raw_answer[start:end + 1], strict=False)


def to_text(value):
    if not value:
        return ""
    return str(value).strip()


def find_number(value):
    """("94.2", 94.2) from "94.2%". Returns (None, None) if there is no number."""
    match = re.search(r"-?\d+(?:\.\d+)?", to_text(value).replace(",", ""))
    if match:
        return match.group(), float(match.group())
    return None, None


def number_in_paper(token, paper_text):
    """True if the number is really written in the paper."""
    pattern = r"(?<![\d.])" + re.escape(token.lstrip("-")) + r"(?!\d|\.\d)"
    return bool(re.search(pattern, paper_text))


def guess_unit(token, paper_text):
    """Look in the paper: is this number written with a % sign or the word "percent"?
    Also works for ranges like "94 to 99 percent" or "94-99%".
    Returns "%" or "" (empty = we do not know)."""
    number = re.escape(token.lstrip("-"))
    pattern = (r"(?<![\d.])" + number +
               r"(?:\s*(?:to|and|-|–)\s*\d+(?:\.\d+)?)?\s*(?:%|percent|per cent)")
    if re.search(pattern, paper_text, re.IGNORECASE):
        return "%"
    return ""


def join_value_and_unit(value, unit):
    """"94" + "%" -> "94%"      "3.5" + "days" -> "3.5 days"      "7" + "" -> "7" """
    if unit == "%":
        return value + "%"
    if unit:
        return value + " " + unit
    return value


def format_change(difference):
    """+2.10 -> "+2.1"   0 -> "+0" """
    text = "%+.2f" % difference
    return text.rstrip("0").rstrip(".")


def bar_widths(old, new, unit):
    """How long the two bars are, from 0 to 100."""
    biggest = max(abs(old), abs(new))
    if unit == "%" and biggest <= 100:
        top = 100.0
    elif biggest:
        top = biggest
    else:
        top = 1.0
    return round(min(100, abs(old) / top * 100), 1), round(min(100, abs(new) / top * 100), 1)


def clean_comparisons(items, paper_text):
    """Keep a row only if BOTH numbers are in the paper. We do the maths here."""
    rows = []
    if not isinstance(items, list):
        return rows

    for item in items:
        if not isinstance(item, dict):
            continue
        old_text, old = find_number(item.get("old"))
        new_text, new = find_number(item.get("new"))
        if old is None or new is None:
            continue
        if not (number_in_paper(old_text, paper_text) and number_in_paper(new_text, paper_text)):
            continue

        unit = to_text(item.get("unit"))
        difference = new - old
        higher_is_better = item.get("higher_is_better")

        good = None       # True = better, False = worse, None = unknown
        if isinstance(higher_is_better, bool) and difference != 0:
            good = (difference > 0) == higher_is_better

        if difference == 0:
            direction = "same"
        elif difference > 0:
            direction = "up"
        else:
            direction = "down"

        if unit == "%":
            change_text = format_change(difference) + " pts"
        elif unit:
            change_text = format_change(difference) + " " + unit
        else:
            change_text = format_change(difference)

        change_pct = None
        if old != 0:
            change_pct = round(difference / abs(old) * 100, 1)

        bar_old, bar_new = bar_widths(old, new, unit)
        rows.append({
            "metric": to_text(item.get("metric")) or "Result",
            "old_label": to_text(item.get("old_label")) or "Before",
            "old": old_text,
            "new_label": to_text(item.get("new_label")) or "After",
            "new": new_text,
            "unit": unit,
            "change_abs": change_text,
            "change_pct": change_pct,
            "direction": direction,
            "good": good,
            "bar_old": bar_old,
            "bar_new": bar_new,
        })
    return rows[:3]


def clean_key_numbers(items, paper_text, used_numbers):
    """Keep a key number only if it is in the paper. Make sure it has its unit."""
    numbers = []
    if not isinstance(items, list):
        return numbers

    for item in items:
        if not isinstance(item, dict):
            continue
        value = to_text(item.get("value"))
        label = to_text(item.get("label"))
        token, ignore = find_number(value)
        if not value or not token or token in used_numbers:
            continue
        if re.fullmatch(r"\d", token):          # one single digit proves nothing
            continue
        if not number_in_paper(token, paper_text):
            continue
        used_numbers.add(token)

        # find the unit: 1) what Gemini wrote, 2) a % inside the value, 3) look in the paper
        unit = to_text(item.get("unit"))
        if not unit and "%" in value:
            unit = "%"
        if not unit:
            unit = guess_unit(token, paper_text)

        if unit:
            shown = join_value_and_unit(token, unit)
        else:
            shown = value                        # no unit found: show it as Gemini wrote it
        numbers.append({"value": shown, "label": label})
    return numbers[:4]


def clean_card(item):
    """Make sure a card is {"short": text, "detailed": text}."""
    if not isinstance(item, dict):
        item = {"short": to_text(item), "detailed": to_text(item)}
    short = to_text(item.get("short"))
    detailed = to_text(item.get("detailed"))
    return {"short": short or detailed or NOT_STATED,
            "detailed": detailed or short or NOT_STATED}


def clean_summary(data, full_text):
    # we check the numbers against the WHOLE paper (not only the parts we sent)
    paper_text = full_text.replace(",", "")

    result = {}
    for name in CARD_NAMES:
        result[name] = clean_card(data.get(name))

    comparisons = clean_comparisons(data.get("comparisons"), paper_text)
    used_numbers = set()
    for row in comparisons:
        used_numbers.add(row["old"])
        used_numbers.add(row["new"])

    result["comparisons"] = comparisons
    result["key_numbers"] = clean_key_numbers(data.get("key_numbers"), paper_text, used_numbers)
    return result


def summarize_paper(pdf_path, api_key, paper_title="", collection_name=""):
    full_text = extract_text(pdf_path)
    if len(full_text.strip()) < MIN_TEXT_LENGTH:
        raise ValueError("Could not extract enough text.")

    text_to_send = pick_text(full_text, collection_name)
    prompt = build_prompt(text_to_send, paper_title)
    last_error = None
    for attempt in range(2):              # try twice, in case the JSON is broken
        try:
            answer = generate_text(prompt, api_key, temperature=0.0, max_output_tokens=4096,
                                   response_mime_type="application/json")
            return clean_summary(parse_json(answer), full_text)
        except ValueError as error:       # a broken JSON is also a ValueError
            last_error = error
            print("[summarizer] bad JSON, trying again:", error)
    raise RuntimeError("Could not build the summary. Try again. (" + str(last_error) + ")")