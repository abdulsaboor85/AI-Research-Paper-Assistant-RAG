"""
summarizer.py  -  write the summary of a paper (5 cards + numbers).

HOW THIS FILE WORKS (easy words)
------------------------------------------------------------
1. Read the whole paper. Cut off the reference list. If it is very long,
   keep the start (70%) and the end (30%).
2. Ask Gemini ONE time to answer in JSON (a computer-friendly format) with:
     5 cards: about, problem, did, results, limits  (each has a "short" and a "detailed" text)
     comparisons: old method vs new method on the same metric
     key_numbers: other important result numbers (each has a value, a unit and a label)
3. CHECK Gemini's work. This is the important part:
     * Every number must really appear in the PDF text, or we drop it.
     * If a number has no unit, we look in the paper for a % sign next to it.
     * WE do the maths (difference, percent, bar widths), not Gemini.
4. If the JSON is broken, we try one more time.

FUNCTION GUIDE
------------------------------------------------------------
   prepare_text          cut references and very long text
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

from extractor import MIN_TEXT_LENGTH, extract_text
from model_config import generate_text

NOT_STATED = "Not stated in the paper."
MAX_CHARS = 60000                      # a longer paper is trimmed (keeps it fast and cheap)
CARD_NAMES = ["about", "problem", "did", "results", "limits"]

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


def prepare_text(full_text):
    """Cut the reference list. Keep only the start and the end of a very long paper."""
    text = full_text.strip()
    matches = list(re.finditer(r"\n\s*(references|bibliography)\s*\n", text, re.IGNORECASE))
    if matches and matches[-1].start() > len(text) * 0.5:
        text = text[:matches[-1].start()]
    text = re.sub(r"\n{3,}", "\n\n", text)

    if len(text) > MAX_CHARS:
        head = text[:int(MAX_CHARS * 0.7)]
        tail = text[-int(MAX_CHARS * 0.3):]
        text = head + "\n\n[... middle of the paper trimmed ...]\n\n" + tail
    return text


def build_prompt(text, title):
    return f"""You are an expert academic tutor. Summarize the research paper below for a university student.

Paper title: "{title}"

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
- "detailed": one paragraph of 4 to 6 sentences.

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
    return json.loads(raw_answer[start:end + 1])


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


def summarize_paper(pdf_path, api_key, paper_title=""):
    full_text = extract_text(pdf_path)
    if len(full_text.strip()) < MIN_TEXT_LENGTH:
        raise ValueError("Could not extract enough text.")

    prompt = build_prompt(prepare_text(full_text), paper_title)
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