"""Prerequisite Extractor: turns a paper into a beginner -> advanced learning roadmap."""

import re

from model_config import call_gemini

STOP_WORDS = ("related work", "methodology", "methods", "approach", "experiments", "results")


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = re.sub(r"\[\d+\]", "", text)
    text = re.sub(r"http\S+", "", text)
    return text.strip()


def extract_abstract(text: str) -> str:
    start = text.lower().find("abstract")
    if start == -1:
        return text[:4000]
    chunk = text[start:start + 6000]
    end = chunk.lower().find("introduction")
    return (chunk[:end] if end != -1 else chunk).strip()


def extract_introduction(text: str) -> str:
    start = text.lower().find("introduction")
    if start == -1:
        return text[:6000]
    chunk = text[start:start + 10000]
    lower = chunk.lower()
    positions = [lower.find(w) for w in STOP_WORDS if w in lower]
    return (chunk[:min(positions)] if positions else chunk).strip()


def build_concept_prompt(abstract: str, intro: str) -> str:
    return f"""
Extract the core concepts required to understand this research paper.

RULES:
- Return 15 to 25 concepts, one per line.
- No explanations, numbering, bullet points, or markdown.
- Focus on technical concepts, theories, algorithms, methods, and prerequisite knowledge.

ABSTRACT:
{abstract}

INTRODUCTION:
{intro}
"""


def build_prerequisite_prompt(concepts: str) -> str:
    return f"""
You are an academic prerequisite extraction system.
Convert the concepts below into a learning roadmap.

RULES:
- Output exactly 12 to 15 prerequisites, ordered from beginner to advanced.
- Format:

1. Topic: Short explanation

- One line per prerequisite. Keep explanations short.
- No markdown, bullet points, headings, or extra text. Output ONLY the numbered list.

CONCEPTS:
{concepts}
"""


def clean_output(text: str) -> str:
    """Remove markdown/duplicates and renumber the list 1, 2, 3..."""
    cleaned, seen = [], set()
    for line in text.split("\n"):
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line.strip())
        line = re.sub(r"^[-*]\s*", "", line)
        line = re.sub(r"^\d+[.)]\s*", "", line)
        if line and line.lower() not in seen:
            seen.add(line.lower())
            cleaned.append(f"{len(cleaned) + 1}. {line}")
    return "\n".join(cleaned)


def extract_prerequisites(text: str, api_key: str) -> str:
    text = clean_text(text)
    concepts = call_gemini(
        build_concept_prompt(extract_abstract(text), extract_introduction(text)),
        api_key, tag="Prereq",
    )
    roadmap = call_gemini(build_prerequisite_prompt(concepts), api_key, tag="Prereq")
    return clean_output(roadmap)