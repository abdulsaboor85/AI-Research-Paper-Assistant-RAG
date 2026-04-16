import sys
import os

# Fix all paths regardless of where you run from
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE_DIR)

from extractor import extract_text
from chunker import chunk_text
from embedder import embed_and_store
from retriever import retrieve_relevant_chunks
from qa_engine import answer_question

def process_pdf(pdf_path):
    print("📄 Extracting text...")
    text = extract_text(pdf_path)
    
    print("✂️ Chunking text...")
    chunks = chunk_text(text)
    
    print("🔢 Embedding and storing...")
    embed_and_store(chunks)
    
    print("✅ PDF processed and ready for questions!")

def ask(question):
    print(f"🔍 Retrieving relevant chunks...")
    chunks = retrieve_relevant_chunks(question)
    
    print("🤖 Generating answer...")
    answer = answer_question(question, chunks)
    
    return answer

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pipeline.py <path_to_pdf>")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    process_pdf(pdf_path)
    
    print("\n--- Q&A Ready! Type 'exit' to quit ---\n")
    while True:
        question = input("Your question: ")
        if question.lower() == "exit":
            break
        answer = ask(question)
        print(f"\nAnswer: {answer}\n")