"""
PATH  ->  pipeline/prerequisite_extractor.py

FYP Module  : AI-Powered Research Paper Assistant (RAG)
Feature     : Prerequisite Extractor
Author      : Abdul Saboor
"""

import os
import re
import sys
import time

import pdfplumber
from dotenv import load_dotenv
from google import genai

from model_config import GEMINI_MODEL_POOL, MAX_RETRIES_PER_MODEL, RETRY_DELAY_SECONDS

load_dotenv()


# =========================================================
# PDF TEXT CLEANING
# =========================================================

def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = re.sub(r"\[\d+\]", "", text)
    text = re.sub(r"http\S+", "", text)
    return text.strip()


def extract_pdf_text(pdf_path: str) -> str:
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return clean_text(text)


# =========================================================
# TITLE / ABSTRACT / INTRODUCTION EXTRACTION
# =========================================================

def extract_title(text: str) -> str:
    for line in text.split("\n")[:20]:
        line = line.strip()
        if 5 < len(line) < 150:
            return line
    return "Research Paper"


def extract_abstract(text: str) -> str:
    lower = text.lower()
    start = lower.find("abstract")
    if start == -1:
        return text[:4000]

    chunk = text[start:start + 6000]
    end   = chunk.lower().find("introduction")
    return (chunk[:end] if end != -1 else chunk).strip()


def extract_introduction(text: str) -> str:
    lower = text.lower()
    start = lower.find("introduction")
    if start == -1:
        return text[:6000]

    chunk       = text[start:start + 10000]
    lower_chunk = chunk.lower()
    stop_words  = ["related work", "methodology", "methods", "approach", "experiments", "results"]

    positions = [lower_chunk.find(w) for w in stop_words if lower_chunk.find(w) != -1]
    if positions:
        chunk = chunk[:min(positions)]
    return chunk.strip()


# =========================================================
# GEMINI CLIENT
# =========================================================

class PrerequisiteExtractor:

    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable not found.")
        self.client = genai.Client(api_key=api_key)

    # ── Model call with fallback + retry ──────────────────

    def call_model(self, prompt: str) -> str:
        last_error = None

        for model in GEMINI_MODEL_POOL:
            for attempt in range(MAX_RETRIES_PER_MODEL):
                try:
                    response = self.client.models.generate_content(model=model, contents=prompt)
                    if response and getattr(response, "text", None):
                        return response.text.strip()
                except Exception as e:
                    last_error = e
                    print(f"[WARNING] {model} failed (attempt {attempt + 1}): {e}")
                    time.sleep(RETRY_DELAY_SECONDS)

        raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")

    # ── Prompts ────────────────────────────────────────────

    def build_concept_prompt(self, title: str, abstract: str, intro: str, keywords: list) -> str:
        return f"""
Extract the core concepts required to understand this research paper.

RULES:
- Return 15 to 25 concepts.
- One concept per line.
- No explanations, numbering, bullet points, or markdown.
- Focus on technical concepts, theories, algorithms, methods, and prerequisite knowledge.

TITLE:
{title}

ABSTRACT:
{abstract}

INTRODUCTION:
{intro}

KEYWORDS:
{", ".join(keywords)}
"""

    def build_prerequisite_prompt(self, concepts: str) -> str:
        return f"""
You are an academic prerequisite extraction system.

Convert the concepts below into a learning roadmap.

RULES:
- Output exactly 12 to 15 prerequisites.
- Order topics from beginner to advanced.
- Format:

1. Topic: Short explanation

- One line per prerequisite. Keep explanations short.
- No markdown, bullet points, headings, or extra text.
- Output ONLY the numbered list.

CONCEPTS:
{concepts}
"""

    # ── Output cleanup ─────────────────────────────────────

    def clean_output(self, text: str) -> str:
        cleaned, seen = [], set()

        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue

            line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
            line = re.sub(r"^[-*]\s*", "", line)
            line = re.sub(r"^\d+[\.\)]\s*", "", line)
            if not line:
                continue

            normalized = line.lower()
            if normalized in seen:
                continue

            seen.add(normalized)
            cleaned.append(f"{len(cleaned) + 1}. {line}")

        return "\n".join(cleaned)

    # ── Main extraction pipeline ───────────────────────────

    def extract(self, text: str) -> str:
        title    = extract_title(text)
        abstract = extract_abstract(text)
        intro    = extract_introduction(text)
        keywords = list(set(re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())))[:20]

        concepts = self.call_model(self.build_concept_prompt(title, abstract, intro, keywords))
        roadmap  = self.call_model(self.build_prerequisite_prompt(concepts))

        return self.clean_output(roadmap)


# =========================================================
# CLI
# =========================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: python prerequisite_extractor.py <pdf_path>")
        return

    pdf_path = sys.argv[1]
    if not os.path.exists(pdf_path):
        print(f"Error: File not found -> {pdf_path}")
        return

    print("\nProcessing PDF...\n")
    text      = extract_pdf_text(pdf_path)
    extractor = PrerequisiteExtractor()
    result    = extractor.extract(text)

    print("\n" + "=" * 70)
    print("PREREQUISITE LEARNING ROADMAP")
    print("=" * 70 + "\n")
    print(result)


if __name__ == "__main__":
    main()