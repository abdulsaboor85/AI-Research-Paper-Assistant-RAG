"""
====================================================
 PATH  →  rag_visualizer.py   (project root)
====================================================

Run:
    python rag_visualizer.py "path/to/paper.pdf" "your question here"

Example:
    python rag_visualizer.py "papers/attention.pdf" "How does self-attention work?"
"""

import os
import sys
import time
import numpy as np
import pdfplumber
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.join(os.path.dirname(__file__), "pipeline"))

from sentence_transformers import SentenceTransformer
from model_config import GEMINI_MODEL_POOL, MAX_RETRIES_PER_MODEL, RETRY_DELAY_SECONDS
from google import genai


# ── Config ────────────────────────────────────────────────────────────────────
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
TOP_K            = 3
VECTOR_PREVIEW   = 8   # number of vector dimensions to show


# ── Display Helpers ───────────────────────────────────────────────────────────

def divider(char="─", width=68):
    print(char * width)

def header(title):
    print()
    divider("═")
    print(f"  {title}")
    divider("═")

def sub(title):
    print()
    divider()
    print(f"  {title}")
    divider()

def fmt_vector(vec):
    preview = "  [ " + ",   ".join(f"{v:+.4f}" for v in vec[:VECTOR_PREVIEW]) + ",  ... ]"
    norm    = f"  norm={np.linalg.norm(vec):.4f}   total dims={len(vec)}"
    return preview, norm

def cosine_similarity(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

def similarity_bar(score, width=28):
    filled = int(max(score, 0) * width)
    bar    = "█" * filled + "░" * (width - filled)
    return f"[{bar}]  {score:.4f}"

def wrap_print(text, indent="  ", width=65):
    words = text.split()
    line  = indent
    for word in words:
        if len(line) + len(word) + 1 > width:
            print(line)
            line = indent
        line += word + " "
    if line.strip():
        print(line)


# ── PDF Extraction ────────────────────────────────────────────────────────────

def extract_text(pdf_path: str) -> str:
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text.strip()


# ── Chunker ───────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size=100, overlap=20):
    words  = text.split()
    chunks = []
    start  = 0
    while start < len(words):
        end   = min(start + chunk_size, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end == len(words):
            break
        start += chunk_size - overlap
    return chunks


# ── LLM Call ─────────────────────────────────────────────────────────────────

def call_llm(question: str, top_chunks: list) -> tuple:
    client  = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    context = "\n\n".join(
        f"[Chunk {i+1}]:\n{chunk}"
        for i, chunk in enumerate(top_chunks)
    )
    prompt = f"""You are a research paper assistant.
Answer the question using ONLY the context below.
If the answer is not in the context, say so clearly.

Context:
{context}

Question: {question}

Answer:"""

    last_error = None
    for model_name in GEMINI_MODEL_POOL:
        for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
            try:
                response = client.models.generate_content(
                    model    = model_name,
                    contents = prompt,
                    config   = {"max_output_tokens": 1024}
                )
                return response.text.strip(), model_name
            except Exception as e:
                last_error = e
                error_str  = str(e)
                if "429" in error_str or "quota" in error_str.lower() or \
                   "503" in error_str or "UNAVAILABLE" in error_str:
                    print(f"    ⚠  [{model_name}] quota/unavailable "
                          f"(attempt {attempt}/{MAX_RETRIES_PER_MODEL}) "
                          f"— retrying in {RETRY_DELAY_SECONDS}s...")
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue
                elif "404" in error_str or "NOT_FOUND" in error_str or \
                     "invalid" in error_str.lower():
                    print(f"    ✗  [{model_name}] not available — skipping...")
                    break
                else:
                    print(f"    ✗  [{model_name}] unexpected error: {e}")
                    break
        print(f"    →  Moving to next model in pool...")
    raise Exception(f"All models failed. Last error: {last_error}")


# ── Main Pipeline Visualizer ──────────────────────────────────────────────────

def run_visualizer(pdf_path: str, question: str):

    filename = os.path.basename(pdf_path)

    # ── Load embedding model ──────────────────────────────────────────────────
    print(f"\n  Loading embedding model  :  {EMBED_MODEL_NAME}")
    model = SentenceTransformer(EMBED_MODEL_NAME)
    print(f"  Vector dimensions        :  384")
    print(f"  PDF                      :  {filename}")
    print(f"  Question                 :  {question}")


    # ════════════════════════════════════════════════════════════════
    #  STEP 1 — Extract text from PDF
    # ════════════════════════════════════════════════════════════════
    header("STEP 1 — EXTRACTING TEXT FROM PDF")

    raw_text = extract_text(pdf_path)
    words    = raw_text.split()
    print(f"\n  File         :  {filename}")
    print(f"  Total words  :  {len(words)}")
    print(f"  Total chars  :  {len(raw_text)}")
    print(f"\n  First 300 characters extracted:\n")
    print(f"  \"{raw_text[:300]}...\"")


    # ════════════════════════════════════════════════════════════════
    #  STEP 2 — Chunk the text
    # ════════════════════════════════════════════════════════════════
    header("STEP 2 — CHUNKING THE TEXT")

    chunks = chunk_text(raw_text, chunk_size=100, overlap=20)

    print(f"\n  Chunk size   :  100 words")
    print(f"  Overlap      :  20 words  (shared between consecutive chunks)")
    print(f"  Total chunks :  {len(chunks)}\n")

    # Show first 4 chunks only to keep output readable
    display_limit = min(4, len(chunks))
    for i in range(display_limit):
        chunk = chunks[i]
        print(f"  ── Chunk {i+1}  ({len(chunk.split())} words) " + "─" * 35)
        wrap_print(f'"{chunk[:180]}{"..." if len(chunk) > 180 else ""}"')
        print()

    if len(chunks) > display_limit:
        print(f"  ... ({len(chunks) - display_limit} more chunks not shown)\n")


    # ════════════════════════════════════════════════════════════════
    #  STEP 3 — Embed each chunk
    # ════════════════════════════════════════════════════════════════
    header("STEP 3 — EMBEDDING CHUNKS INTO VECTORS")

    print(f"\n  Model   :  {EMBED_MODEL_NAME}")
    print(f"  Each chunk of text → a 384-dim float vector")
    print(f"  Showing first {VECTOR_PREVIEW} dimensions of each vector\n")

    chunk_vectors = []
    for i, chunk in enumerate(chunks):
        vec = model.encode(chunk)
        chunk_vectors.append(vec)

    # Display vectors for first 4 chunks only
    for i in range(display_limit):
        preview, norm = fmt_vector(chunk_vectors[i])
        print(f"  Chunk {i+1}:")
        print(f"    Text   : \"{chunks[i][:70]}{'...' if len(chunks[i]) > 70 else ''}\"")
        print(f"    Vector :")
        print(f"    {preview}")
        print(f"    {norm}")
        print()

    if len(chunks) > display_limit:
        print(f"  ... ({len(chunks) - display_limit} more chunk vectors computed but not shown)\n")


    # ════════════════════════════════════════════════════════════════
    #  STEP 4 — Embed the question
    # ════════════════════════════════════════════════════════════════
    header("STEP 4 — EMBEDDING THE QUESTION INTO A VECTOR")

    print(f"\n  Question : \"{question}\"\n")

    q_vec         = model.encode(question)
    preview, norm = fmt_vector(q_vec)

    print(f"  Question Vector:")
    print(f"    {preview}")
    print(f"    {norm}")
    print(f"\n  This vector captures the semantic meaning of the question.")
    print(f"  It will be compared against every chunk vector.")


    # ════════════════════════════════════════════════════════════════
    #  STEP 5 — Cosine Similarity
    # ════════════════════════════════════════════════════════════════
    header("STEP 5 — COSINE SIMILARITY: QUESTION vs EVERY CHUNK")

    print(f"""
  Cosine similarity = angle between two vectors in 384D space.

    score = 1.00  →  vectors point in same direction (same meaning)
    score = 0.50  →  somewhat related
    score = 0.00  →  completely unrelated
    score < 0.00  →  opposite meaning
""")

    similarities = []
    for i, (chunk, c_vec) in enumerate(zip(chunks, chunk_vectors)):
        sim = cosine_similarity(q_vec, c_vec)
        similarities.append((sim, i, chunk))

    # Show all similarities sorted
    ranked = sorted(similarities, key=lambda x: x[0], reverse=True)

    print(f"  All {len(chunks)} chunks ranked by similarity:\n")
    for rank, (sim, orig_idx, chunk) in enumerate(ranked):
        marker = "  ✓ SELECTED" if rank < TOP_K else "    skipped "
        print(f"  Rank {rank+1:>2}  |  Chunk {orig_idx+1:>2}  |  "
              f"{similarity_bar(sim)}  |{marker}")
        print(f"          \"{chunk[:60]}{'...' if len(chunk) > 60 else ''}\"")
        print()


    # ════════════════════════════════════════════════════════════════
    #  STEP 6 — Show Top-K
    # ════════════════════════════════════════════════════════════════
    header(f"STEP 6 — TOP {TOP_K} CHUNKS SELECTED FOR LLM")

    top_k      = ranked[:TOP_K]
    top_chunks = []

    print(f"\n  These {TOP_K} chunks scored highest against the question vector.\n")
    for rank, (sim, orig_idx, chunk) in enumerate(top_k):
        print(f"  ── Selected Chunk {rank+1}  "
              f"(original Chunk {orig_idx+1}, similarity: {sim:.4f}) " + "─"*10)
        wrap_print(f'"{chunk}"')
        print()
        top_chunks.append(chunk)

    total_words = sum(len(c.split()) for c in top_chunks)
    print(f"  Total context sent to LLM  :  {total_words} words")
    print(f"  Question sent to LLM       :  \"{question}\"")


    # ════════════════════════════════════════════════════════════════
    #  STEP 7 — LLM call
    # ════════════════════════════════════════════════════════════════
    header("STEP 7 — CALLING LLM WITH TOP-K CHUNKS + QUESTION")

    print(f"\n  Model pool tried in order:")
    for i, m in enumerate(GEMINI_MODEL_POOL):
        print(f"    {i+1}. {m}")

    print(f"\n  Prompt structure:\n")
    print(f"  ┌{'─'*62}┐")
    print(f"  │  ROLE    : Research paper assistant                       │")
    print(f"  │  CONTEXT : Top {TOP_K} chunks ({total_words} words)                          │")
    print(f"  │  QUESTION: {question[:50]:<50}  │")
    print(f"  │  OUTPUT  : Answer using ONLY the provided context         │")
    print(f"  └{'─'*62}┘")

    print(f"\n  Calling LLM...\n")

    answer, used_model = call_llm(question, top_chunks)


    # ════════════════════════════════════════════════════════════════
    #  STEP 8 — Final Answer
    # ════════════════════════════════════════════════════════════════
    header("STEP 8 — FINAL ANSWER")

    print(f"\n  Model used  :  {used_model}")
    print(f"  Question    :  {question}")
    print()
    divider()
    print()
    wrap_print(answer, indent="  ", width=68)
    print()
    divider("═")
    print(f"  Done. Full RAG pipeline visualized.")
    divider("═")
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":

    if len(sys.argv) < 3:
        print("\n  [ERROR] Missing arguments.")
        print("  Usage   :  python rag_visualizer.py \"path/to/paper.pdf\" \"your question\"")
        print("  Example :  python rag_visualizer.py \"papers/attention.pdf\" \"How does attention work?\"\n")
        sys.exit(1)

    pdf_path = sys.argv[1]
    question = sys.argv[2]

    if not os.path.exists(pdf_path):
        print(f"\n  [ERROR] File not found: {pdf_path}\n")
        sys.exit(1)

    if not pdf_path.lower().endswith(".pdf"):
        print(f"\n  [ERROR] Must be a PDF file.\n")
        sys.exit(1)

    if not os.getenv("GEMINI_API_KEY"):
        print(f"\n  [ERROR] GEMINI_API_KEY not found in .env\n")
        sys.exit(1)

    run_visualizer(pdf_path, question)
