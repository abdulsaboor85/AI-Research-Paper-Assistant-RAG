import os
import sys
import time
import pdfplumber
from dotenv import load_dotenv
from google import genai

from model_config import (
    GEMINI_MODEL_POOL,
    MAX_RETRIES_PER_MODEL,
    RETRY_DELAY_SECONDS
)

load_dotenv()


# -----------------------------
# PDF TEXT EXTRACTION
# -----------------------------
def extract_pdf_text(pdf_path):
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text.strip()


def extract_abstract(text):
    """
    Simple heuristic: extract first 1500-2500 chars as abstract proxy
    (you can improve later with section detection)
    """
    return text[:2500]


def extract_keywords(text):
    """
    Lightweight keyword extraction fallback (no ML dependency required here)
    """
    words = text.lower().split()
    freq = {}

    stopwords = set([
        "the", "is", "in", "and", "to", "of", "a", "for", "on",
        "we", "this", "that", "with", "as", "by", "an", "are"
    ])

    for w in words:
        if w.isalpha() and w not in stopwords and len(w) > 3:
            freq[w] = freq.get(w, 0) + 1

    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_words[:10]]


# -----------------------------
# GEMINI CLIENT
# -----------------------------
class PrerequisiteExtractor:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key:
            raise ValueError("❌ GEMINI_API_KEY not set in .env")

        self.client = genai.Client(api_key=api_key)

    def build_prompt(self, title, abstract, keywords, references=""):
        return f"""
You are a senior machine learning professor and curriculum designer.

Your task is to extract the MINIMUM COMPLETE SET of prerequisites required to understand this research paper.

This is NOT a summary.
This is NOT a keyword extraction.
This is a CURRICULUM DESIGN task.

================================================
🎯 CORE OBJECTIVE
================================================
Produce a CLEAN, NON-REDUNDANT, HIGH-LEVEL learning roadmap of prerequisites required to fully understand the paper.

The output must represent a university-level study plan.

================================================
🚨 CRITICAL RULES (MOST IMPORTANT PART)
================================================

1) STRICT CONCEPT COMPRESSION (VERY IMPORTANT):
- ALWAYS merge related sub-concepts into ONE concept

MANDATORY MERGING RULES:

❌ NEVER split these:

- RNN, LSTM, GRU → Recurrent Neural Networks
- Attention, Self-Attention, Multi-Head Attention, QKV, Scaled Dot-Product → Transformer Attention System
- Feedforward NN, MLP → Feedforward Neural Networks
- Encoder + Decoder + Seq2Seq → Sequence-to-Sequence Modeling
- Layer Norm + Residual Connections + FFN → Transformer Block Architecture

2) NO MICRO-CONCEPTS:
- Do NOT include internal components of architectures
- Do NOT explain mechanisms separately
- Keep only HIGH-LEVEL concepts

3) STRICT LIMIT:
- Output MUST contain 12 to 18 items ONLY
- If more appear, MERGE further

4) STRICT ORDERING:
- Arrange from MOST FUNDAMENTAL → MOST ADVANCED
- Each item must build logically on the previous one

5) NO REDUNDANCY:
- No repeated ideas in different wording
- No overlapping concepts

6) NO LOW-LEVEL DETAILS:
- Avoid things like:
  softmax, activation functions, small formulas, sub-mechanisms

================================================
📤 OUTPUT FORMAT
================================================

Return ONLY a numbered list:

1) Concept Name: 1-line explanation
2) Concept Name: 1-line explanation
3) Concept Name: 1-line explanation

NO headings, NO JSON, NO extra text.

================================================
📚 COVERAGE CHECKLIST
================================================

Ensure coverage of:
- Mathematics (Linear Algebra, Calculus, Probability if needed)
- Machine Learning fundamentals
- Neural Networks (high-level only)
- Sequence modeling (if applicable)
- Transformer architecture (if applicable)
- Training + optimization concepts
- Evaluation metrics (if applicable)
- System concepts (GPU, distributed training if relevant)

================================================
🧠 QUALITY GOAL
================================================

Your output must be:
- Minimal
- Complete
- Non-redundant
- High-level
- Easy to study from
- Suitable as a prerequisite syllabus for a university student

================================================
📄 INPUT
================================================

TITLE:
{title}

ABSTRACT:
{abstract}

KEYWORDS:
{", ".join(keywords)}

REFERENCES:
{references if references else "Not provided"}
"""

    def call_model(self, prompt):
        last_error = None

        for model in GEMINI_MODEL_POOL:
            for attempt in range(MAX_RETRIES_PER_MODEL):
                try:
                    response = self.client.models.generate_content(
                        model=model,
                        contents=prompt
                    )

                    if response and response.text:
                        return response.text

                except Exception as e:
                    last_error = e
                    time.sleep(RETRY_DELAY_SECONDS)

        raise RuntimeError(f"All models failed. Last error: {last_error}")

    def extract(self, text):
        title = "Research Paper"
        abstract = extract_abstract(text)
        keywords = extract_keywords(text)

        prompt = self.build_prompt(title, abstract, keywords)

        result = self.call_model(prompt)

        return result


# -----------------------------
# MAIN
# -----------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python prerequisite_extractor.py <pdf_path>")
        return

    pdf_path = sys.argv[1]

    print(f"\n📄 Processing: {pdf_path}\n")

    text = extract_pdf_text(pdf_path)

    extractor = PrerequisiteExtractor()
    result = extractor.extract(text)

    print("\n================ PREREQUISITES ================\n")
    print(result)


if __name__ == "__main__":
    main()