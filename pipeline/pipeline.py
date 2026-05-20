# pipeline.py
import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE_DIR)

from extractor import extract_text
from chunker import chunk_text
from embedder import embed_and_store
from retriever import retrieve_relevant_chunks
from qa_engine import answer_question


SUMMARY_TRIGGERS = {
    "summarize", "summarise", "summary", "summarization",
    "overview", "outline", "brief", "tldr", "tl;dr",
    "what is this paper about", "what is this document about",
    "what does this paper cover", "what does this document cover",
}

SECTION_SUMMARY_HINTS = {
    "abstract",
    "introduction",
    "intro",
    "conclusion",
    "methodology",
    "methods",
    "results",
    "discussion",
    "related work",
    "background",
    "literature review",
    "limitations",
    "section",
    "chapter",
}

FULL_PAPER_SUMMARY_HINTS = {
    "full paper",
    "entire paper",
    "whole paper",
    "overall paper",
    "paper summary",
    "document summary",
    "give me a summary",
    "give me the summary",
}


def is_summary_request(question: str) -> bool:
    """Return True if the question is asking for a summary."""
    normalized = question.lower().strip()
    return any(trigger in normalized for trigger in SUMMARY_TRIGGERS)


def is_section_summary_request(question: str) -> bool:
    """Return True if the user is asking for a specific section summary."""
    normalized = question.lower().strip()
    return is_summary_request(normalized) and any(
        hint in normalized for hint in SECTION_SUMMARY_HINTS
    )


def is_full_paper_summary_request(question: str) -> bool:
    """Return True if the user is asking for a whole-paper summary."""
    normalized = question.lower().strip()

    if not is_summary_request(normalized):
        return False

    if any(hint in normalized for hint in FULL_PAPER_SUMMARY_HINTS):
        return True

    return not any(hint in normalized for hint in SECTION_SUMMARY_HINTS)


def process_pdf(pdf_path: str) -> None:
    """Extract, chunk, embed, and store a research paper PDF."""

    if not os.path.exists(pdf_path):
        print(f"Error: File not found — {pdf_path}")
        sys.exit(1)

    if not pdf_path.lower().endswith(".pdf"):
        print(f"Error: File must be a PDF — {pdf_path}")
        sys.exit(1)

    print("📄 Extracting text...")
    text = extract_text(pdf_path)

    if not text or not text.strip():
        print("Error: No text could be extracted from the PDF.")
        sys.exit(1)

    print("✂️  Chunking text...")
    chunks = chunk_text(text)

    if not chunks:
        print("Error: Text chunking produced no chunks.")
        sys.exit(1)

    print("🔢 Embedding and storing...")
    embed_and_store(chunks)

    print("✅ PDF processed successfully!")


def ask(question: str) -> str:
    """Retrieve relevant chunks and generate a grounded answer."""

    print("🔍 Retrieving relevant chunks...")
    chunks = retrieve_relevant_chunks(question, top_k=7)

    if not chunks:
        return "No relevant content could be retrieved from the document for this question."

    print("🤖 Generating answer...")
    answer = answer_question(question, chunks)

    return answer


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pipeline.py <pdf_path>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    process_pdf(pdf_path)

    print("\n--- Q&A Ready (type 'exit' to quit) ---\n")

    while True:
        try:
            question = input("Your question: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            break

        if not question:
            print("Please enter a question.\n")
            continue

        if question.lower() == "exit":
            print("Goodbye!")
            break

        if is_full_paper_summary_request(question):
            print("\nAnswer:\nSummarization is handled separately. Please use the summary feature for this request.\n")
            continue

        answer = ask(question)
        print(f"\nAnswer:\n{answer}\n")
