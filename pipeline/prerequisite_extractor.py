"""
prerequisite_extractor.py  -  make a learning roadmap for a paper (12 to 15 topics).

HOW THIS FILE WORKS (easy words)
------------------------------------------------------------
1. Clean the paper text and cut out the title, a SHORT part of the abstract
   and a SHORT part of the introduction (this keeps the tokens low).
2. Ask Gemini ONE time: "Think about the core concepts, then write a roadmap
   from beginner to advanced, as a numbered list:   1. Topic: short explanation"
3. Clean the answer: remove markdown and duplicates, number it again from 1.

FUNCTION GUIDE
------------------------------------------------------------
   clean_text             tidy the paper text
   find_title             the first line that looks like a title
   find_abstract          the abstract part of the paper (short)
   find_introduction      the introduction part of the paper (short)
   roadmap_prompt         the ONE instruction for Gemini
   clean_roadmap          clean and renumber the answer
   extract_prerequisites  the main function
"""

import re

from model_config import generate_text

ABSTRACT_LIMIT = 2000       # the most letters we take from the abstract
INTRO_LIMIT = 4000          # the most letters we take from the introduction
MIN_INTRO_LETTERS = 500     # a shorter introduction is probably a wrong cut, so we keep more


def clean_text(text):
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = re.sub(r"\[\d+\]", "", text)
    text = re.sub(r"http\S+", "", text)
    return text.strip()


def find_title(raw_text):
    """The first line (of the first 20) with a sensible length. Use the RAW text."""
    for line in raw_text.split("\n")[:20]:
        line = line.strip()
        if 5 < len(line) < 150:
            return line
    return "Research Paper"


def find_abstract(text):
    start = text.lower().find("abstract")
    if start == -1:
        return text[:ABSTRACT_LIMIT]
    piece = text[start:start + ABSTRACT_LIMIT]
    end = piece.lower().find("introduction")
    if end != -1:
        piece = piece[:end]
    return piece.strip()


def find_introduction(text):
    start = text.lower().find("introduction")
    if start == -1:
        return text[:INTRO_LIMIT]
    piece = text[start:start + INTRO_LIMIT]
    lower = piece.lower()

    stop_positions = []
    for word in ["related work", "methodology", "methods", "approach", "experiments", "results"]:
        position = lower.find(word)
        if position != -1:
            stop_positions.append(position)
    if stop_positions:
        cut_at = min(stop_positions)
        if cut_at >= MIN_INTRO_LETTERS:       # a very early cut is probably a wrong one
            piece = piece[:cut_at]
    return piece.strip()


def roadmap_prompt(title, abstract, intro):
    return f"""
You are an academic prerequisite extraction system.

Read the paper opening below. Think silently about the core concepts a student
must know to understand this paper (theories, algorithms, methods).
Then pick the 12 to 15 most important ones and write a learning roadmap.

RULES:
- Output exactly 12 to 15 prerequisites.
- Order topics from beginner to advanced.
- Format:

1. Topic: Short explanation

- One line per prerequisite. Keep explanations short.
- No markdown, bullet points, headings, or extra text.
- Output ONLY the numbered list.

TITLE:
{title}

ABSTRACT:
{abstract}

INTRODUCTION:
{intro}
"""


def clean_roadmap(text):
    """Remove markdown and numbers, drop duplicate lines, number again from 1."""
    cleaned = []
    seen = set()
    for line in text.split("\n"):
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line.strip())
        line = re.sub(r"^[-*]\s*", "", line)
        line = re.sub(r"^\d+[.)]\s*", "", line)
        if not line or line.lower() in seen:
            continue
        seen.add(line.lower())
        cleaned.append(str(len(cleaned) + 1) + ". " + line)
    return "\n".join(cleaned)


def extract_prerequisites(raw_text, api_key=None):
    title = find_title(raw_text)
    text = clean_text(raw_text)

    roadmap = generate_text(roadmap_prompt(title, find_abstract(text), find_introduction(text)), api_key)
    return clean_roadmap(roadmap)