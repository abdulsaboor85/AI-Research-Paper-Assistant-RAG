import os
import re
import sys
import time
from collections import Counter

import pdfplumber
from dotenv import load_dotenv
from google import genai

from model_config import (
    GEMINI_MODEL_POOL,
    MAX_RETRIES_PER_MODEL,
    RETRY_DELAY_SECONDS
)

load_dotenv()


# =========================================================
# PDF TEXT EXTRACTION
# =========================================================

def clean_text(text: str) -> str:
    """
    Clean broken PDF text.
    """

    # remove multiple spaces
    text = re.sub(r"\s+", " ", text)

    # fix weird line joins
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)

    # remove references like [12]
    text = re.sub(r"\[\d+\]", "", text)

    # remove URLs
    text = re.sub(r"http\S+", "", text)

    return text.strip()


def extract_pdf_text(pdf_path):
    text = ""

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()

            if page_text:
                text += page_text + "\n"

    text = clean_text(text)

    return text


# =========================================================
# TITLE EXTRACTION
# =========================================================

def extract_title(text: str) -> str:
    """
    Try to extract paper title from first lines.
    """

    lines = text.split("\n")

    cleaned = []

    for line in lines[:20]:
        line = line.strip()

        if len(line) < 5:
            continue

        if len(line.split()) > 20:
            continue

        cleaned.append(line)

    if cleaned:
        return cleaned[0]

    return "Research Paper"


# =========================================================
# ABSTRACT EXTRACTION
# =========================================================

def extract_abstract(text):
    """
    Extract abstract section properly.
    """

    lower = text.lower()

    start = lower.find("abstract")

    if start == -1:
        return text[:3000]

    abstract_text = text[start:start + 4000]

    # stop at introduction
    intro_idx = abstract_text.lower().find("introduction")

    if intro_idx != -1:
        abstract_text = abstract_text[:intro_idx]

    return abstract_text.strip()


# =========================================================
# KEYWORD EXTRACTION
# =========================================================

STOPWORDS = {
    "the", "is", "in", "and", "to", "of", "a", "for",
    "on", "we", "this", "that", "with", "as", "by",
    "an", "are", "be", "from", "or", "it", "our",
    "their", "using", "used", "into", "these",
    "can", "has", "have", "had", "was", "were",
    "will", "which", "than", "also", "such"
}


def extract_keywords(text, top_n=20):
    """
    Better keyword extraction.
    """

    words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())

    filtered = [
        w for w in words
        if w not in STOPWORDS
    ]

    freq = Counter(filtered)

    keywords = [
        word for word, _ in freq.most_common(top_n)
    ]

    return keywords


# =========================================================
# GEMINI CLIENT
# =========================================================

class PrerequisiteExtractor:

    def __init__(self):

        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key:
            raise ValueError("❌ GEMINI_API_KEY not found in .env")

        self.client = genai.Client(api_key=api_key)

    # =====================================================
    # PROMPT
    # =====================================================

    def build_prompt(self, title, abstract, keywords):

        return f"""
You are an expert AI professor and curriculum designer.

Your task is to create a HIGH-QUALITY prerequisite roadmap for understanding a research paper.

IMPORTANT:
This is NOT summarization.
This is NOT keyword extraction.

You must identify the MINIMUM COMPLETE SET of topics a university student should learn BEFORE reading this paper.

==================================================
RULES
==================================================

1. OUTPUT ONLY 12-18 ITEMS

2. ORDER:
Start from basic concepts → advanced concepts.

3. EACH ITEM FORMAT:
1. Topic Name: Short explanation

4. KEEP TOPICS HIGH-LEVEL
GOOD:
- Linear Algebra
- Probability
- Neural Networks
- Transformers
- Sequence Modeling

BAD:
- Softmax
- Query vectors
- Positional encoding equations
- Attention weights

5. MERGE RELATED TOPICS

MERGE THESE:
- RNN + LSTM + GRU → Recurrent Neural Networks
- Self Attention + Multi Head Attention + QKV → Transformer Attention Mechanisms
- Encoder + Decoder + Seq2Seq → Sequence-to-Sequence Learning
- Residual + LayerNorm + FFN → Transformer Architecture

6. REMOVE REDUNDANCY

7. NO HEADINGS
NO JSON
NO EXTRA TEXT

==================================================
PAPER TITLE
==================================================

{title}

==================================================
ABSTRACT
==================================================

{abstract}

==================================================
KEYWORDS
==================================================

{", ".join(keywords)}
"""

    # =====================================================
    # GEMINI CALL
    # =====================================================

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
                        return response.text.strip()

                except Exception as e:
                    last_error = e
                    time.sleep(RETRY_DELAY_SECONDS)

        raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")

    # =====================================================
    # CLEAN OUTPUT
    # =====================================================

    def clean_output(self, text: str) -> str:
        """
        Final cleanup for Gemini response.
        """

        lines = text.split("\n")

        cleaned = []

        seen = set()

        for line in lines:

            line = line.strip()

            if not line:
                continue

            # remove markdown bullets
            line = re.sub(r"^[-*]\s*", "", line)

            # normalize numbering
            line = re.sub(r"^\d+\)", "", line).strip()

            # ensure numbering exists
            if not re.match(r"^\d+\.", line):
                line = f"{len(cleaned)+1}. {line}"

            # duplicate removal
            lower = line.lower()

            if lower in seen:
                continue

            seen.add(lower)

            cleaned.append(line)

        return "\n".join(cleaned)

    # =====================================================
    # MAIN EXTRACTION
    # =====================================================

    def extract(self, text):

        title = extract_title(text)

        abstract = extract_abstract(text)

        keywords = extract_keywords(text)

        prompt = self.build_prompt(
            title=title,
            abstract=abstract,
            keywords=keywords
        )

        result = self.call_model(prompt)

        result = self.clean_output(result)

        return result


# =========================================================
# MAIN
# =========================================================

def main():

    if len(sys.argv) < 2:
        print("Usage:")
        print("python prerequisite_extractor.py <pdf_path>")
        return

    pdf_path = sys.argv[1]

    print("\n🚀 Starting Analysis...\n")

    text = extract_pdf_text(pdf_path)

    if len(text.strip()) < 100:
        print("❌ Failed to extract enough text.")
        return

    extractor = PrerequisiteExtractor()

    result = extractor.extract(text)

    print("\n" + "=" * 80)
    print("🎓 WHAT YOU SHOULD LEARN BEFORE THIS PAPER")
    print("=" * 80 + "\n")

    print(result)


if __name__ == "__main__":
    main()