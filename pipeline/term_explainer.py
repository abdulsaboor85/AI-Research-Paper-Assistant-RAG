"""
term_explainer.py  -  explain a term, a formula or a table from the paper.

HOW THIS FILE WORKS (easy words)
------------------------------------------------------------
 1. Python looks at what you selected: a table, a formula or a plain term (no AI).
 2. Python finds the right part of the paper (no AI).
      * a TABLE: table_reader.py reads the rows by their position on the page,
        so every number stays in its own row. If that fails, we use the chunks.
 3. Gemini is asked ONE time and answers in JSON.
 4. Python CHECKS the answer:
      * a term: is it a real concept? (a person's name or a result like
        "28.4 BLEU" is NOT a concept, so it can never go to Memory)
      * a formula: it gets a "say it out loud" sentence, 3 to 5 parts and a symbol list.
        Every part must really be written inside the clean formula, or it is dropped.
        Every example line is calculated again (numbers, + - * / ( ),
        sqrt, exp, log, sin, cos, sum, max, min, softmax). The example is also
        thrown away if it skips a function that the formula really has.
        A wrong example is worse than no example.
      * a table: every number must be in the paper, and every decimal number
        in the PDF table should be in the rebuilt table (links and DOIs are ignored).
      * all texts: strong words like "proves" become "suggests".
 5. app.py saves the answer in the cache/ folder.

FUNCTION GUIDE
------------------------------------------------------------
 DETECTING WHAT WAS SELECTED
   looks_like_formula        does the text look like math?
   detect_kind               table, formula or term?
   term_key                  short key used in the cache file name
   starts_with_number        is it a result like "28.4 BLEU"?
 FINDING THE RIGHT PART OF THE PAPER
   number_of                 "chunk_12" -> 12
   numbers_of                chunk ids -> chunk numbers
   pair_number               chunk number of an (id, text) pair
   window_numbers            chunk numbers around a centre chunk
   search_ids                chunks with the closest meaning
   ids_containing            chunks that contain an exact phrase
   read_chunks               read chunks by number, in paper order
   join_two_chunks           glue two neighbour chunks, remove the overlap
   glue_chunks               glue many chunks into one text
   term_context              paper text for a plain term
   table_hits                chunks that really mention this table
   pick_caption              chunk number where the caption starts
   is_caption_chunk          does this chunk start the table caption?
   table_context             paper text for a table
   pick_formula_chunk        the chunk that fits the formula best
   formula_context           paper text for a formula
   get_context               paper text for any kind
 PROMPTS
   term_prompt               the question for a term
   formula_prompt            the question for a formula
   table_prompt              the question for a table
   build_prompt              choose the right question
 ASK GEMINI AND CHECK
   ask_gemini                ask Gemini, read the JSON answer
   to_bool                   Gemini's true/false to Python True/False
   clean_pairs               keep only good symbol/meaning pairs
   clean_lines               keep only lines that have text
   clean_rows                give every table row the same width
   softmax_list              softmax of a list of numbers
   calculation_is_safe       only allowed signs and function names?
   check_math_line           calculate one example line again
   check_math                check all example lines
   example_follows_formula   does the example use every function of the formula?
   squash                    text without spaces, to compare formula pieces
   clean_parts               keep only parts that are inside the formula
   unmatched_numbers         table numbers that are not in the paper
   missing_decimals          PDF decimals that are not in the table
   soften                    change "proves" into "suggests"
   clean_formula_fields      clean the formula part of the answer
   clean_table_fields        clean the table part of the answer
   clean_answer              clean everything Gemini returned
   empty_result              an answer with every part empty
   explain_term              the main function
"""

import hashlib
import math
import re

from embedder import client, model
from model_config import generate_text
from retriever import retrieve_relevant_chunks
from summarizer import number_in_paper, parse_json, to_text
from table_reader import LAYOUT_MARK, read_table_text

# Change this text when you change a question (prompt) or a check.
# Old saved answers are then made again by themselves.
EXPLAIN_VERSION = "v5"

NOT_IN_PAPER = "Not explained in the retrieved paper text."
NO_TEXT = "(No related text was found in this paper.)"
SEARCH_PREFIX = "Represent this sentence for searching relevant passages: "

# How much of the paper we read. Small numbers = fewer tokens.
TERM_CHUNKS = 6
FORMULA_BEFORE = 1       # chunks BEFORE the formula chunk
FORMULA_AFTER = 3        # chunks AFTER it (the "where x is ..." part)
FORMULA_EXTRA = 2        # extra chunks that match the meaning
TABLE_BEFORE = 1
TABLE_AFTER = 14         # backup method only: the table body comes after its caption
MENTION_CHUNKS = 2       # chunks of normal text that talk about the table
MAX_CONTEXT_CHARS = 5000
TABLE_CONTEXT_CHARS = 9000
MAX_SIDE_CHARS = 1000

# Gemini counts its "thinking" inside the output tokens, so a big table needs more room
NORMAL_OUTPUT_TOKENS = 4096
TABLE_OUTPUT_TOKENS = 12000

MAX_SYMBOLS = 18
MAX_PARTS = 6
MAX_COLUMNS = 14
MAX_ROWS = 60
MAX_LOST_NUMBERS = 4     # the most "lost" numbers we name in a warning

# = ∑ ∫ √ ∈ ∂ ∇ ≤ ≥ ≈ × · → ∏ ±   (written as codes, so every editor saves them safely)
STRONG_SIGNS = "=\u2211\u222b\u221a\u2208\u2202\u2207\u2264\u2265\u2248\u00d7\u00b7\u2192\u220f\u00b1"

TABLE_START = re.compile(r"^\s*(?:table|tab\.)\s*([0-9]+|[ivxlc]+)\b", re.IGNORECASE)

NUMBER_CELL = re.compile(r"^-?\d+(?:\.\d+)?%?$")
NUMBER_ONLY = re.compile(r"^-?\d+(?:\.\d+)?$")
DECIMAL_NUMBER = re.compile(r"(?<![\d.])\d+\.\d+(?!\d)")
RESULT_NUMBER = re.compile(r"^[-+]?\d+(?:\.\d+)?%?(?:\s|$)")

# Links and DOIs like 10.1371/journal.pone... look like decimal numbers but are not table values
LINK_TEXT = re.compile(r"https?://\S+|doi\.org/\S+|\b10\.\d{4,}/\S+", re.IGNORECASE)

# The math tools an example line may use (longest names first, see calculation_is_safe)
MATH_NAME_ORDER = ["softmax", "sqrt", "sum", "max", "min", "exp", "log", "sin", "cos"]

# The words a formula may contain. If the formula has one, the example MUST use it too.
FORMULA_WORDS = ["softmax", "sqrt", "exp", "log", "sin", "cos", "sum", "concat", "max", "min"]

# Strong words that a table or a formula can never prove
OVERCLAIMS = [("proves", "suggests"), ("proved", "suggested"),
              ("proven", "shown"), ("prove", "suggest")]

# The shape of the answer we ask Gemini for
TERM_SCHEMA = '{"is_concept": true, "simple": "...", "from_paper": "...", "example": "..."}'

FORMULA_SCHEMA = """{
  "clean": "the formula rebuilt as plain text",
  "read_aloud": "the formula said in words, one sentence",
  "simple": "...",
  "parts": [{"symbol": "a piece copied from clean", "meaning": "..."}],
  "symbols": [{"symbol": "Q", "meaning": "..."}],
  "from_paper": "...",
  "example": "one sentence",
  "example_source": "paper or made-up",
  "example_steps": ["2 * 3 = 6"]
}"""

TABLE_SCHEMA = """{
  "what": "...",
  "takeaway": "...",
  "columns": ["..."],
  "rows": [["..."]],
  "legend": [{"symbol": "n", "meaning": "..."}],
  "simple": "...",
  "warning": ""
}"""


def softmax_list(values):
    """Softmax of a list of numbers (a single number counts as a list of one)."""
    if isinstance(values, (int, float)):
        values = [values]
    biggest = max(values)
    parts = []
    for value in values:
        parts.append(math.exp(value - biggest))
    total = sum(parts)
    result = []
    for part in parts:
        result.append(part / total)
    return result


# The only names eval may use. There are no builtins, so nothing else can run.
EVAL_NAMES = {
    "__builtins__": {},
    "sqrt": math.sqrt, "exp": math.exp, "log": math.log,
    "sin": math.sin, "cos": math.cos,
    "softmax": softmax_list, "sum": sum, "max": max, "min": min,
}


# ---------------------------------------------------------------
# Detecting what was selected
# ---------------------------------------------------------------
def looks_like_formula(text):
    """True if the text has math signs, a Greek letter, a power like x^2, or a call like f(x, y)."""
    for letter in text:
        if letter in STRONG_SIGNS:
            return True
        if "\u0370" <= letter <= "\u03ff":          # the Greek letters
            return True
    if re.search(r"[A-Za-z0-9]\s*[\^_]\s*[A-Za-z0-9{(]", text):
        return True
    if re.search(r"\b[A-Za-z]{1,12}\s*\(\s*[A-Za-z0-9]{1,3}\s*(?:,\s*[A-Za-z0-9]{1,3}\s*)*\)", text):
        return True
    return False


def detect_kind(term):
    """Table first (the label is clear), then formula, else a plain term."""
    if TABLE_START.match(term):
        return "table"
    if looks_like_formula(term):
        return "formula"
    return "term"


def term_key(term):
    """A short key for one question. app.py uses it as part of the saved file name."""
    text = re.sub(r"\s+", " ", term)
    text = text.strip().lower()
    raw = EXPLAIN_VERSION + "|" + text
    digest = hashlib.sha1(raw.encode("utf-8"))
    return digest.hexdigest()[:20]


def starts_with_number(text):
    """True for a result like "28.4 BLEU" or "94%". Such a text is a number, not a concept.
    "3D convolution" and "Word2Vec" are NOT caught (no space after the number)."""
    return bool(RESULT_NUMBER.match(text.strip()))


# ---------------------------------------------------------------
# Finding the right part of the paper
# ---------------------------------------------------------------
def number_of(chunk_id):
    """"chunk_12" -> 12"""
    return int(chunk_id.split("_")[-1])


def numbers_of(ids):
    numbers = []
    for chunk_id in ids:
        numbers.append(number_of(chunk_id))
    return numbers


def pair_number(pair):
    """The number of an (id, text) pair. Used for sorting."""
    return number_of(pair[0])


def window_numbers(center, before, after):
    """The chunk numbers from (center - before) to (center + after). No negative numbers."""
    numbers = []
    for number in range(center - before, center + after + 1):
        if number >= 0:
            numbers.append(number)
    return numbers


def search_ids(collection, text, count):
    """The ids of the chunks whose MEANING is closest to the text."""
    numbers = model.encode([SEARCH_PREFIX + text]).tolist()
    try:
        results = collection.query(query_embeddings=numbers, n_results=count)
    except Exception as error:
        print("[explainer] meaning search failed:", error)
        return []
    return results["ids"][0]


def ids_containing(collection, phrase):
    """The ids of the chunks that contain this exact phrase (letters must match)."""
    try:
        result = collection.get(where_document={"$contains": phrase})
    except Exception as error:
        print("[explainer] text search failed:", error)
        return []
    return result["ids"]


def read_chunks(collection, numbers):
    """Read chunks by number. Returns (id, text) pairs in paper order."""
    if len(numbers) == 0:
        return []
    ids = []
    for number in numbers:
        ids.append("chunk_" + str(number))
    try:
        result = collection.get(ids=ids)
    except Exception as error:
        print("[explainer] could not read chunks:", error)
        return []

    pairs = []
    for i in range(len(result["ids"])):
        pairs.append((result["ids"][i], result["documents"][i]))
    pairs.sort(key=pair_number)
    return pairs


def join_two_chunks(first, second):
    """Neighbour chunks share a few letters (the overlap). Glue them without repeating those letters."""
    biggest = min(len(first), len(second), 60)
    for size in range(biggest, 9, -1):
        if first.endswith(second[:size]):
            return first + second[size:]
    return first + "\n" + second


def glue_chunks(pairs):
    """Glue chunks into one text. Chunks that are not neighbours get a [...] between them."""
    text = ""
    last_number = -10
    for chunk_id, document in pairs:
        number = number_of(chunk_id)
        if text == "":
            text = document
        elif number == last_number + 1:
            text = join_two_chunks(text, document)
        else:
            text = text + "\n[...]\n" + document
        last_number = number
    return text


def term_context(collection_name, term):
    """A plain term: the chunks that mention it, plus the chunk before and after each."""
    collection = client.get_or_create_collection(collection_name)

    ids = ids_containing(collection, term)[:2]             # chunks with the exact word
    for chunk_id in search_ids(collection, term, 3):       # chunks with the closest meaning
        if chunk_id not in ids:
            ids.append(chunk_id)

    numbers = []
    for chunk_id in ids[:4]:
        for number in window_numbers(number_of(chunk_id), 1, 1):
            if number not in numbers:
                numbers.append(number)

    pairs = read_chunks(collection, numbers)
    if len(pairs) == 0:                                    # backup: the old search
        chunks = retrieve_relevant_chunks(term, collection_name=collection_name, top_k=TERM_CHUNKS)
        return "\n---\n".join(chunks[:TERM_CHUNKS]), "", len(chunks[:TERM_CHUNKS])
    return glue_chunks(pairs), "", len(pairs)


def table_hits(collection, token):
    """All chunks that really mention this table (a search for table 1 must not return table 10)."""
    phrases = ["Table " + token, "TABLE " + token.upper(), "Table " + token.upper()]
    numbers = []
    for phrase in phrases:
        for chunk_id in ids_containing(collection, phrase):
            number = number_of(chunk_id)
            if number not in numbers:
                numbers.append(number)

    mention = re.compile(r"\btable\s+" + re.escape(token) + r"\b", re.IGNORECASE)
    hits = []
    for pair in read_chunks(collection, numbers):
        if mention.search(pair[1]):
            hits.append(pair)
    return hits


def pick_caption(hits, token):
    """The number of the chunk where the caption starts, like "Table 1: Results ...". None if not found."""
    start = r"(?:^|\n)\s*table\s+" + re.escape(token)
    strict = re.compile(start + r"\s*[:.]", re.IGNORECASE)      # "Table 1:" or "Table 1."
    loose = re.compile(start + r"\b", re.IGNORECASE)            # a line that starts with "Table 1"
    for pattern in [strict, loose]:
        for chunk_id, document in hits:
            if pattern.search(document):
                return number_of(chunk_id)
    return None


def is_caption_chunk(document, token):
    """True if a line of this chunk starts with "Table <token>" (so it is the caption, not a mention)."""
    pattern = re.compile(r"(?:^|\n)\s*table\s+" + re.escape(token) + r"\b", re.IGNORECASE)
    return bool(pattern.search(document))


def table_context(collection, term, pdf_path):
    """A table: the rows (main) and normal text about the table (side). None if nothing is found.
    First we read the rows by position from the PDF. If that fails, we use the chunks."""
    match = TABLE_START.match(term)
    token = match.group(1)
    hits = table_hits(collection, token)

    # BEST WAY: the real rows, read by position (every number stays in its own row)
    if pdf_path:
        layout_text = read_table_text(pdf_path, token)
        if layout_text:
            mentions = []
            for pair in hits:
                if len(mentions) < MENTION_CHUNKS and not is_caption_chunk(pair[1], token):
                    mentions.append(pair)
            print("[explainer] table", token, "read by position")
            return layout_text, glue_chunks(mentions), 1 + len(mentions)

    # BACKUP: the caption chunk and the chunks after it
    center = pick_caption(hits, token)
    if center is None:
        return None

    window = window_numbers(center, TABLE_BEFORE, TABLE_AFTER)
    table_pairs = read_chunks(collection, window)

    mentions = []
    for pair in hits:
        if number_of(pair[0]) not in window and len(mentions) < MENTION_CHUNKS:
            mentions.append(pair)
    print("[explainer] table", token, "read from chunks (backup)")
    return glue_chunks(table_pairs), glue_chunks(mentions), len(table_pairs) + len(mentions)


def pick_formula_chunk(ids, pairs, formula):
    """Of the chunks found by meaning, the one that shares most words with the formula."""
    words = set(re.findall(r"[a-z]{3,}", formula.lower()))
    texts = {}
    for chunk_id, document in pairs:
        texts[chunk_id] = document.lower()

    best_id = ids[0]
    best_score = -1
    for chunk_id in ids:
        score = 0
        if chunk_id in texts:
            for word in words:
                if word in texts[chunk_id]:
                    score += 1
        if score > best_score:
            best_score = score
            best_id = chunk_id
    return number_of(best_id)


def formula_context(collection, formula):
    """A formula: its chunk + the chunks after it + a few chunks that match in meaning."""
    ids = search_ids(collection, formula, 6)
    if len(ids) == 0:
        return None

    found = read_chunks(collection, numbers_of(ids))
    best = pick_formula_chunk(ids, found, formula)
    wanted = window_numbers(best, FORMULA_BEFORE, FORMULA_AFTER)

    extras = 0
    for chunk_id in ids:
        number = number_of(chunk_id)
        if number not in wanted and extras < FORMULA_EXTRA:
            wanted.append(number)
            extras += 1

    pairs = read_chunks(collection, wanted)
    return glue_chunks(pairs), "", len(pairs)


def get_context(kind, term, collection_name, pdf_path):
    """The paper text for this kind. If the special search finds nothing, we use the normal search."""
    collection = client.get_or_create_collection(collection_name)
    result = None
    if kind == "table":
        result = table_context(collection, term, pdf_path)
    elif kind == "formula":
        result = formula_context(collection, term)
    if result is None:
        result = term_context(collection_name, term)
    return result


# ---------------------------------------------------------------
# Prompts (the questions we send to Gemini)
# ---------------------------------------------------------------
def term_prompt(term, context, title):
    return f"""You are a patient tutor. Explain one term from the research paper "{title}" to a complete beginner.

TERM: "{term}"

PAPER TEXT (parts of the paper, may be cut):
{context}

Return ONLY valid JSON in exactly this shape:
{TERM_SCHEMA}

RULES:
- is_concept: true ONLY if the term is a real idea, method, model, metric or technical word that a student can learn.
  false if it is a person's name, an author, a university, a company, an email, a citation, a normal non-technical word,
  or a RESULT such as a score or a number ("28.4 BLEU", "94%", "0.746 accuracy").
- simple: 1 to 2 SHORT sentences. What the term means in general, in very easy words. No jargon.
  Do not use the paper here. If is_concept is false, say in one simple sentence what it is
  (for example "This is the name of an author of the paper." or, for "28.4 BLEU", what the metric BLEU measures).
- from_paper: 2 to 3 SHORT sentences. What the term means IN THIS PAPER, using the paper's own facts,
  names and numbers from the text above. Clear and to the point. Never add anything the text does not say.
  For a result like "28.4 BLEU", say which model or task got it and what it is compared with.
  If the text only mentions it, write "This paper mentions '{term}' but does not explain it in detail."
  If the text has nothing about it, write "This term does not appear to be discussed in this paper."
- example: if is_concept is true, start with "Example:" then 2 to 3 SHORT sentences about ONE real-world
  situation, very easy and clear. Use small simple numbers when the term is a measure.
  Pick a situation that fits THIS term. Do NOT reuse a phone or voice-to-text app unless the term is about phones.
  The example must be ethical and safe for everyone: no relationships, romance, music, dance, violence,
  politics, religion, alcohol or anything sensitive. Good topics: school, cooking, shopping, weather, travel, a library.
  If is_concept is false, use "".
- Never use the words "prove", "proves" or "proof". Say "shows" or "suggests".
- Plain text only: no markdown. Never invent what the paper says."""


def formula_prompt(formula, context, title):
    return f"""You are a patient tutor. Explain ONE formula from the research paper "{title}" to a beginner.

SELECTED FORMULA (copied from the PDF, so symbols can be broken, merged or in the wrong order):
{formula}

PAPER TEXT AROUND THE FORMULA (may be cut; the meaning of symbols is often written after the formula, after the word "where"):
{context}

Return ONLY valid JSON in exactly this shape:
{FORMULA_SCHEMA}

RULES:
- clean: rebuild the formula as clean plain text. Use ^ for powers, _ for subscripts, sqrt( ) and /.
  Check it against the paper text. Everything below must be based on THIS clean formula.
- read_aloud: ONE sentence that says the formula in words, the way a teacher reads it aloud.
  Write "sum", "divided by", "squared", "equals". Never use math signs in this sentence.
- simple: 2 to 3 SHORT sentences in very easy words. First say what kind of formula it is
  (for example "a score", "a probability", "a loss", "a position code") and what it does in THIS paper
  (what goes in, what comes out, and whether higher or lower is better, only if the paper says so).
- parts: 3 to 5 pieces of the clean formula, in the order a student should read them.
  "symbol" is the piece COPIED EXACTLY from your clean formula (the same letters and signs).
  "meaning" is ONE easy sentence: what this piece does to the numbers.
  Together the pieces cover the whole formula. If the formula is very short, use 2 pieces.
- symbols: EVERY symbol, function and operator a beginner may not know, in order of appearance.
  Also include every set, every index (i, j, n, z), every bar sign like |C| (the size of a set),
  every hat or subscript (like y_hat or x_i), and what a sum runs over.
  "meaning" has at most 15 words and tells what the variable stands for here.
  If the paper does not define it, give the usual meaning and end with "(usual meaning, not stated in the paper)".
- from_paper: 1 to 3 SHORT sentences. What the paper text above says about THIS formula
  (usually the "where ..." part and what it is used for). Use only the text above.
  If the text says nothing about it, write exactly "{NOT_IN_PAPER}"
- example: ONE short sentence that introduces a tiny example and says what the numbers stand for.
  If the paper text gives real values for the symbols, use THEM and set example_source to "paper".
  If it does not, use tiny whole numbers and set example_source to "made-up".
- example_steps: 2 to 5 lines that follow the formula IN ORDER, one line for each part of the formula,
  written as "calculation = result". The result must be ONE number.
  You may use ONLY: numbers, + - * / ( ), and these tools: sqrt( ) exp( ) log( ) sin( ) cos( )
  sum([1, 2]) max([1, 2]) min([1, 2]) softmax([6]) and softmax([2, 1])[0] (the [0] picks the first value).
  Never use letters, ^, powers, or any other function.
  VERY IMPORTANT: every function that is in the formula (softmax, sqrt, sin, sum...) MUST appear in a line
  with real numbers. Never skip a part of the formula. Never replace a part with a different operation.
  For a sum, write the real addition, for example "0.4 + 0.6 = 1", then the division, then the last step.
  If the formula has matrices, vectors, concat, several heads or anything you cannot calculate with
  the tools above, use "" for example and [] for example_steps. No example is better than a wrong example.
  Do not number the lines.
- Never use the words "prove", "proves" or "proof".
- Plain text only: no markdown, no LaTeX. Never invent what the paper says."""


def table_prompt(term, table_text, mention_text, title):
    if mention_text.strip() == "":
        mention_text = "(none found)"

    if table_text.startswith(LAYOUT_MARK):
        how = ("The table text below was read by POSITION on the page. Each line is ONE row of the table "
               "and ' | ' marks a gap between two columns. A header that wraps onto 2 lines is one header. "
               "The caption comes first.")
    else:
        how = ("The table text below was copied from the PDF and is jumbled: words of different column "
               "headers can be mixed together, and the values of each column are listed one after another, "
               "not row by row. The caption comes first.")

    return f"""You are a patient tutor. Explain ONE table from the research paper "{title}" to a beginner.

SELECTED: {term}

TABLE TEXT. {how}
{table_text}

NORMAL TEXT THAT MENTIONS THE TABLE:
{mention_text}

Return ONLY valid JSON in exactly this shape:
{TABLE_SCHEMA}

RULES:
- what: the easy translation. 1 to 3 SHORT sentences in very easy words: what the table compares and how.
- takeaway: the main result and WHY, 1 to 2 SHORT sentences. Name the best row and its number.
  Use only the table and the text above. If the paper does not say why, give only the result. Never invent a reason.
  Say "in this table" or "in this experiment". Never use "prove", "proves", "proof", "always" or "all models".
- columns and rows: rebuild the WHOLE table. "columns" are the column names. Every row is a list with
  exactly one cell per column.
  * Keep EVERY row of the table text. Never stop early and never skip a row. Count the rows first.
  * Keep EVERY column. Count the numbers in a full row to know how many columns there are.
  * If one header sits above several columns (for example "Accuracy" above "ADR" and "AR"),
    write one column for each, like "Accuracy ADR" and "Accuracy AR".
  * If rows are in groups with a group label (for example ML, PLMs), add a FIRST column named "Group"
    and repeat the group label in every row of that group. Do not make the label a row of its own.
  * Copy every cell from the table text. Fix only clear symbol damage (for example n2 -> n^2).
    Never invent a value. A value that is really missing is "-".
- If the table text is jumbled (not read by position), each column is a SEPARATE list. Count the values of
  each list. If a list has fewer values than there are rows, the missing rows are EMPTY cells (use "-").
  Never shift a value into another column or another row to fill a gap.
- If one value is clearly shared by two columns (written once, like one cost for both tasks),
  repeat it in both columns.
- Use every decimal number of the table text. Do not drop a number.
- warning: if you are NOT sure about some cells, name the exact values and rows that are unsure.
  Example: "Not sure which row 38.1 belongs to." If you are sure, use "".
- legend: the meaning of every letter, symbol and abbreviation used in the table (from the caption and the text).
  If the table uses notation like O(n), explain it in plain words.
- simple: how to read the table. 1 to 2 SHORT sentences.
- Plain text only: no markdown. Never invent what the paper says."""


def build_prompt(kind, term, main_text, side_text, title):
    if kind == "formula":
        return formula_prompt(term, main_text, title)
    if kind == "table":
        return table_prompt(term, main_text, side_text, title)
    return term_prompt(term, main_text, title)


# ---------------------------------------------------------------
# Ask Gemini and check the answer
# ---------------------------------------------------------------
def ask_gemini(prompt, api_key, max_tokens):
    """Ask Gemini and read the JSON answer. We try twice, in case the JSON is broken."""
    last_error = None
    for attempt in range(2):
        try:
            answer = generate_text(prompt, api_key, temperature=0.0, max_output_tokens=max_tokens,
                                   response_mime_type="application/json")
            return parse_json(answer)
        except ValueError as error:
            last_error = error
            print("[explainer] bad JSON, trying again:", error)
    raise RuntimeError("Could not build the explanation. Try again. (" + str(last_error) + ")")


def to_bool(value):
    """true / false from Gemini -> True / False. If Gemini says nothing, we say True."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ["false", "no", "0"]:
        return False
    return True


def clean_pairs(items, limit):
    """Keep only entries like {"symbol": "...", "meaning": "..."} where both have text."""
    result = []
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = to_text(item.get("symbol"))
        meaning = to_text(item.get("meaning"))
        if symbol and meaning:
            result.append({"symbol": symbol, "meaning": meaning})
    return result[:limit]


def clean_lines(items, limit):
    """Keep only the lines that have text."""
    result = []
    if not isinstance(items, list):
        return result
    for item in items:
        line = to_text(item)
        if line:
            result.append(line)
    return result[:limit]


def clean_rows(items, width):
    """Every row gets exactly "width" cells (short rows are filled with empty cells)."""
    rows = []
    if not isinstance(items, list):
        return rows
    for item in items:
        if not isinstance(item, list):
            continue
        cells = []
        for cell in item:
            cells.append(to_text(cell))
        while len(cells) < width:
            cells.append("")
        rows.append(cells[:width])
    return rows[:MAX_ROWS]


def calculation_is_safe(calculation):
    """True only if the calculation has numbers, + - * / ( ) , [ ] and our math names.
    This must be true BEFORE we use eval, so nothing dangerous can run."""
    if len(calculation) > 100 or "**" in calculation:      # a power could freeze the computer
        return False
    if re.search(r"\]\s*\*|\*\s*\[", calculation):         # [1] * 999999999 could fill the memory
        return False

    leftover = calculation
    for name in MATH_NAME_ORDER:                           # longest names first (softmax before max)
        leftover = leftover.replace(name, "")
    return re.fullmatch(r"[0-9.\s+\-*/(),\[\]]*", leftover) is not None


def check_math_line(line):
    """Calculate "calculation = result" again. Returns (the line, True if we could check it).
    A line we cannot calculate (letters, ^, an unknown function, a list as result) is NOT trusted.
    If the result is wrong, we write the right one."""
    if line.count("=") != 1:
        return line, False

    parts = line.split("=")
    calculation = parts[0].strip()
    claimed_text = parts[1].strip()
    if calculation == "" or not NUMBER_ONLY.match(claimed_text):
        return line, False
    if not calculation_is_safe(calculation):
        return line, False

    try:
        correct = eval(calculation, EVAL_NAMES, {})
    except Exception:
        return line, False

    if isinstance(correct, list) and len(correct) == 1:    # softmax([6]) gives a list of one
        correct = correct[0]
    if isinstance(correct, bool) or not isinstance(correct, (int, float)):
        return line, False

    claimed = float(claimed_text)
    allowed = max(0.01, abs(correct) * 0.005)               # a rounded result is fine
    if abs(correct - claimed) <= allowed:
        return line, True

    fixed = "%.4f" % correct
    fixed = fixed.rstrip("0")
    fixed = fixed.rstrip(".")
    return calculation + " = " + fixed, True


def check_math(lines):
    """Check all example lines. Returns (the lines, how many we could check)."""
    new_lines = []
    checked = 0
    for line in lines:
        new_line, was_checked = check_math_line(line)
        new_lines.append(new_line)
        if was_checked:
            checked += 1
    return new_lines, checked


def example_follows_formula(clean_formula, lines):
    """False if the formula has a function (softmax, sin, sum...) that no example line uses.
    This catches an example that skips the hard part of the formula."""
    formula = clean_formula.lower()
    all_steps = " ".join(lines).lower()
    for word in FORMULA_WORDS:
        if word in formula and word not in all_steps:
            if word == "sum" and "+" in all_steps:     # a sum written as a real addition is fine
                continue
            return False
    return True


def squash(text):
    """Lowercase text without spaces, underscores and braces, so two formula pieces can be compared."""
    return re.sub(r"[\s_{}]+", "", text.lower())


def clean_parts(items, clean_formula):
    """Keep only the parts that are really written inside the clean formula.
    Gemini cannot invent a part. With fewer than 2 good parts we show none."""
    pairs = clean_pairs(items, MAX_PARTS)
    whole = squash(clean_formula)

    kept = []
    for pair in pairs:
        if squash(pair["symbol"]) in whole:
            kept.append(pair)
    if len(kept) < 2:
        return []
    return kept


def unmatched_numbers(rows, paper_text):
    """How many number cells of the table are NOT written in the paper text."""
    text = paper_text.replace(",", "")
    missing = 0
    for row in rows:
        for cell in row:
            if NUMBER_CELL.match(cell):
                token = cell.rstrip("%")
                if not number_in_paper(token, text):
                    missing += 1
    return missing


def missing_decimals(table_text, rows):
    """The OTHER direction: decimal numbers that are in the PDF table text
    but are NOT in any cell of the rebuilt table. Returns a short list of texts.
    Links and DOIs are removed first, because their numbers are not table values."""
    cells = []
    for row in rows:
        for cell in row:
            cells.append(cell)
    all_cells = " ".join(cells).replace(",", "")

    table_without_links = LINK_TEXT.sub(" ", table_text)

    lost = []
    for number in DECIMAL_NUMBER.findall(table_without_links.replace(",", "")):
        if number in lost:
            continue
        if not number_in_paper(number, all_cells):
            lost.append(number)
    return lost[:MAX_LOST_NUMBERS]


def soften(text):
    """Gemini sometimes writes "proves". One experiment never proves anything, so we say "suggests"."""
    for strong, soft in OVERCLAIMS:
        text = re.sub(r"\b" + strong + r"\b", soft, text)
        text = re.sub(r"\b" + strong.capitalize() + r"\b", soft.capitalize(), text)
    return text


def clean_formula_fields(data):
    """The extra parts of a formula answer.
    The number example is kept ONLY if every line was really checked by Python
    AND the example uses every function of the formula."""
    clean_formula = to_text(data.get("clean"))
    lines = clean_lines(data.get("example_steps"), 6)
    example_lines, checked = check_math(lines)

    if len(example_lines) == 0 or checked != len(example_lines):
        example_lines = []          # not all lines are trusted, so we hide the example
        checked = 0
    elif not example_follows_formula(clean_formula, example_lines):
        example_lines = []          # the example skips a part of the formula
        checked = 0

    source = "made-up"
    if to_text(data.get("example_source")).lower() == "paper":
        source = "paper"

    return {
        "clean": clean_formula,
        "read_aloud": soften(to_text(data.get("read_aloud"))),
        "parts": clean_parts(data.get("parts"), clean_formula),
        "symbols": clean_pairs(data.get("symbols"), MAX_SYMBOLS),
        "example_steps": example_lines,
        "example_source": source,
        "math_checked": checked,
    }


def clean_table_fields(data, paper_text, table_text):
    columns = clean_lines(data.get("columns"), MAX_COLUMNS)
    rows = clean_rows(data.get("rows"), len(columns))
    if len(columns) == 0:
        rows = []

    notice = to_text(data.get("warning"))

    missing = unmatched_numbers(rows, paper_text)
    if missing > 0:
        notice = notice + " " + str(missing) + " number(s) in this table could not be found in the paper text."

    if len(rows) > 0:
        lost = missing_decimals(table_text, rows)
        if len(lost) > 0:
            notice = (notice + " These numbers are near the table in the PDF, but not in the rebuilt table: " +
                      ", ".join(lost) + ". They may come from normal text, so please check the PDF.")

    return {
        "what": soften(to_text(data.get("what"))),
        "takeaway": soften(to_text(data.get("takeaway"))),
        "columns": columns,
        "rows": rows,
        "legend": clean_pairs(data.get("legend"), MAX_SYMBOLS),
        "notice": notice.strip(),
    }


def clean_answer(kind, data, main_text, side_text):
    """Clean everything Gemini returned. The names below are the ones the browser reads."""
    paper_text = main_text + " " + side_text
    answer = {
        "from_paper": soften(to_text(data.get("from_paper")) or NOT_IN_PAPER),
        "simple_explanation": soften(to_text(data.get("simple")) or "No simple explanation was returned."),
        "real_world_example": soften(to_text(data.get("example"))),
    }

    if kind == "term":
        answer["is_concept"] = to_bool(data.get("is_concept"))
        if not answer["is_concept"]:
            answer["real_world_example"] = ""
    elif kind == "formula":
        fields = clean_formula_fields(data)
        answer.update(fields)
        if len(fields["example_steps"]) == 0:
            answer["real_world_example"] = ""      # no trusted numbers, so no example
    elif kind == "table":
        answer.update(clean_table_fields(data, paper_text, main_text))
    return answer


def empty_result(term, kind, count):
    """Every part exists in every answer (empty if not used), so the browser never meets a missing part."""
    return {
        "term": term, "kind": kind, "found_in_paper": count > 0, "chunks_used": count,
        "is_concept": True,
        "from_paper": "", "simple_explanation": "", "real_world_example": "",
        "what": "", "clean": "", "read_aloud": "", "parts": [], "symbols": [], "steps": [],
        "example_steps": [], "math_checked": 0,
        "columns": [], "rows": [], "legend": [], "takeaway": "", "notice": "",
    }


def explain_term(term, collection_name, api_key, paper_title="", pdf_path=""):
    text = term or ""
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    if not text:
        raise ValueError("Term cannot be empty.")

    kind = detect_kind(text)
    main_text, side_text, count = get_context(kind, text, collection_name, pdf_path)

    # a table needs more room than a term or a formula
    if kind == "table":
        main_text = main_text[:TABLE_CONTEXT_CHARS]
        max_tokens = TABLE_OUTPUT_TOKENS
    else:
        main_text = main_text[:MAX_CONTEXT_CHARS]
        max_tokens = NORMAL_OUTPUT_TOKENS
    side_text = side_text[:MAX_SIDE_CHARS]
    if main_text.strip() == "":
        main_text = NO_TEXT

    data = ask_gemini(build_prompt(kind, text, main_text, side_text, paper_title), api_key, max_tokens)

    result = empty_result(text, kind, count)
    result.update(clean_answer(kind, data, main_text, side_text))

    # a result like "28.4 BLEU" is a number, not a concept: it must never go to Memory
    if kind == "term" and starts_with_number(text):
        result["is_concept"] = False
        result["real_world_example"] = ""
    return result