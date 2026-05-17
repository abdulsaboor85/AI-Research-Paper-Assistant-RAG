"""
====================================================
 PATH  ->  src/analyze_pdf.py
====================================================

Run from terminal:
    python src/analyze_pdf.py "path/to/your/paper.pdf"

Example:
    python src/analyze_pdf.py "D:/papers/attention_is_all_you_need.pdf"
"""

import os
import sys
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

sys.path.append(os.path.join(PROJECT_ROOT, "pipeline"))

import pdfplumber
from difficulty_scorer import analyze_difficulty


def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extracts all text from a PDF using pdfplumber.
    (Same library already in your pipeline)
    """
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text.strip()


def print_result(result: dict, pdf_path: str):
    filename = os.path.basename(pdf_path)

    print("\n" + "=" * 55)
    print(f"  FILE  :  {filename}")
    print("=" * 55)
    print(f"  Final Score      :  {result['final_score']} / 10")
    print(f"  Difficulty Label :  {result['difficulty_label']}")
    print("-" * 55)
    print("  Component Scores  (each out of 10):")
    print(f"    1. Readability      :  {result['scores']['readability']}")
    print(f"    2. Uncommon Words   :  {result['scores']['uncommon_words']}")
    print(f"    3. Technical Terms  :  {result['scores']['technical_terms']}")
    print(f"    4. LLM Perception   :  {result['scores']['llm_perception']}")
    print("-" * 55)
    print("  Paper Stats:")
    print(f"    Total Sentences    :  {result['breakdown']['total_sentences']}")
    print(f"    Total Words        :  {result['breakdown']['total_words']}")
    print(f"    Uncommon Word %    :  {result['breakdown']['uncommon_word_pct']}%")
    print(f"    Technical Term %   :  {result['breakdown']['technical_term_pct']}%")
    print("=" * 55 + "\n")


def main():
    if len(sys.argv) < 2:
        print("\n[ERROR] No PDF path provided.")
        print("Usage:  python src/analyze_pdf.py \"path/to/paper.pdf\"\n")
        sys.exit(1)

    pdf_path = sys.argv[1]

    if not os.path.exists(pdf_path):
        print(f"\n[ERROR] File not found: {pdf_path}\n")
        sys.exit(1)

    if not pdf_path.lower().endswith(".pdf"):
        print(f"\n[ERROR] File must be a PDF: {pdf_path}\n")
        sys.exit(1)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("\n[ERROR] GEMINI_API_KEY not found in .env file.\n")
        sys.exit(1)

    print(f"\n Extracting text from PDF...")
    text = extract_text_from_pdf(pdf_path)

    if not text or len(text) < 100:
        print("\n[ERROR] Could not extract enough text from the PDF.\n")
        sys.exit(1)

    print(f" Extracted {len(text.split())} words from {os.path.basename(pdf_path)}")
    print(f" Running difficulty analysis... (Gemini call may take a few seconds)\n")

    result = analyze_difficulty(
        full_text = text,
        api_key   = api_key,
    )

    print_result(result, pdf_path)


if __name__ == "__main__":
    main()
