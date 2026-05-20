"""Analyze a paper's difficulty score from the command line."""

import os
import sys

from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE_DIR = os.path.join(PROJECT_ROOT, "pipeline")

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
sys.path.append(PIPELINE_DIR)

from difficulty_scorer import analyze_difficulty
from extractor import extract_text


def print_result(result: dict, pdf_path: str) -> None:
    print(f"\n{'=' * 55}\n  FILE  :  {os.path.basename(pdf_path)}\n{'=' * 55}")
    print(f"  Final Score      :  {result['final_score']} / 10")
    print(f"  Difficulty Label :  {result['difficulty_label']}")
    print(f"{'-' * 55}\n  Component Scores  (each out of 10):")
    for index, key in enumerate(("readability", "uncommon_words", "technical_terms", "llm_perception"), start=1):
        print(f"    {index}. {key.replace('_', ' ').title():<16}:  {result['scores'][key]}")
    print(f"{'-' * 55}\n  Paper Stats:")
    print(f"    Total Sentences    :  {result['breakdown']['total_sentences']}")
    print(f"    Total Words        :  {result['breakdown']['total_words']}")
    print(f"    Uncommon Word %    :  {result['breakdown']['uncommon_word_pct']}%")
    print(f"    Technical Term %   :  {result['breakdown']['technical_term_pct']}%")
    print(f"{'=' * 55}\n")


def main() -> None:
    if len(sys.argv) < 2:
        print('\n[ERROR] Usage: python src/analyze_pdf.py "path/to/paper.pdf"\n')
        raise SystemExit(1)

    pdf_path = sys.argv[1]
    if not os.path.exists(pdf_path) or not pdf_path.lower().endswith(".pdf"):
        print(f"\n[ERROR] Invalid PDF path: {pdf_path}\n")
        raise SystemExit(1)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("\n[ERROR] GEMINI_API_KEY not found in .env file.\n")
        raise SystemExit(1)

    print("\n Extracting text from PDF...")
    text = extract_text(pdf_path)
    if len(text) < 100:
        print("\n[ERROR] Could not extract enough text from the PDF.\n")
        raise SystemExit(1)

    print(f" Extracted {len(text.split())} words from {os.path.basename(pdf_path)}")
    print(" Running difficulty analysis... (Gemini call may take a few seconds)\n")
    print_result(analyze_difficulty(full_text=text, api_key=api_key), pdf_path)


if __name__ == "__main__":
    main()
