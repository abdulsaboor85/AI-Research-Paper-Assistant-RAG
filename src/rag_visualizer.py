"""
====================================================
 PATH  ->  src/rag_visualizer.py
====================================================

Runs the full RAG pipeline visually and exports
a Word document showing every step.

Run:
    python src/rag_visualizer.py "path/to/paper.pdf" "your question"

Example:
    python src/rag_visualizer.py "papers/attention.pdf" "How does self-attention work?"

Output:
    reports/<paper-name>__<question>/rag_report.docx
"""

import os
import sys
import re
import json
import time
import subprocess
import numpy as np
import pdfplumber
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
sys.path.append(os.path.join(PROJECT_ROOT, "pipeline"))

from sentence_transformers import SentenceTransformer
import google.genai as genai
from model_config import GEMINI_MODEL_POOL, MAX_RETRIES_PER_MODEL, RETRY_DELAY_SECONDS

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
TOP_K            = 3
VECTOR_PREVIEW   = 8


def safe_folder_name(value: str, max_length: int = 80) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return (value[:max_length].strip("_") or "untitled")


def build_report_dir(pdf_path: str, question: str) -> str:
    paper_name = safe_folder_name(os.path.splitext(os.path.basename(pdf_path))[0])
    question_name = safe_folder_name(question, max_length=120)
    folder_name = f"{paper_name}__{question_name}"
    report_dir = os.path.join(REPORTS_DIR, folder_name)

    if os.path.exists(report_dir):
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        report_dir = os.path.join(REPORTS_DIR, f"{folder_name}__{timestamp}")

    return report_dir


# ─────────────────────────────────────────────────────────────────────────────
#  PDF Text Extraction  (fix for joined words like "hellomynameis")
# ─────────────────────────────────────────────────────────────────────────────

def extract_text(pdf_path: str) -> str:
    """
    Extracts text from PDF using pdfplumber with word-level spacing fix.
    Uses extract_words() instead of extract_text() to correctly reconstruct
    words with proper spaces — fixes the "hellomynameis" problem.
    """
    all_lines = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(
                x_tolerance     = 3,
                y_tolerance     = 3,
                keep_blank_chars = False,
            )
            if not words:
                continue

            # Group words into lines by their top-y position
            lines     = {}
            for word in words:
                y_key = round(word["top"], 1)
                lines.setdefault(y_key, []).append(word)

            # Sort lines top to bottom, words left to right within each line
            for y in sorted(lines.keys()):
                line_words = sorted(lines[y], key=lambda w: w["x0"])
                line_text  = " ".join(w["text"] for w in line_words)
                all_lines.append(line_text)

    return "\n".join(all_lines).strip()


# ─────────────────────────────────────────────────────────────────────────────
#  Chunker
# ─────────────────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 100, overlap: int = 20) -> list:
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


# ─────────────────────────────────────────────────────────────────────────────
#  Cosine Similarity
# ─────────────────────────────────────────────────────────────────────────────

def cosine_similarity(a, b) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


# ─────────────────────────────────────────────────────────────────────────────
#  Calculate detailed similarity breakdown (for visualization)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_similarity_breakdown(question_vec, chunk_vec):
    """
    Calculate detailed similarity breakdown:
    - Dot product
    - Norms
    - Final cosine similarity score
    """
    q_vec_arr = np.array(question_vec)
    c_vec_arr = np.array(chunk_vec)
    
    dot_product = float(np.dot(q_vec_arr, c_vec_arr))
    q_norm = float(np.linalg.norm(q_vec_arr))
    c_norm = float(np.linalg.norm(c_vec_arr))
    similarity = dot_product / (q_norm * c_norm)
    
    return {
        "dot_product": round(dot_product, 6),
        "question_norm": round(q_norm, 6),
        "chunk_norm": round(c_norm, 6),
        "similarity_score": round(similarity, 6),
        "formula_breakdown": f"cos(θ) = {round(dot_product, 6)} / ({round(q_norm, 6)} × {round(c_norm, 6)}) = {round(similarity, 6)}"
    }


# ─────────────────────────────────────────────────────────────────────────────
#  LLM Call  (shared model pool from model_config.py)
# ─────────────────────────────────────────────────────────────────────────────

def call_llm(question: str, top_chunks: list) -> tuple:
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
                    model=model_name,
                    contents=prompt,
                    config={"max_output_tokens": 1024}
                )
                print(f"  ✓  [{model_name}] answered successfully")
                return response.text.strip(), model_name

            except Exception as e:
                last_error = e
                error_str  = str(e)
                if "429" in error_str or "quota" in error_str.lower() or \
                   "503" in error_str or "UNAVAILABLE" in error_str:
                    print(f"  ⚠  [{model_name}] quota/unavailable "
                          f"(attempt {attempt}/{MAX_RETRIES_PER_MODEL}) "
                          f"— retrying in {RETRY_DELAY_SECONDS}s...")
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue
                elif "404" in error_str or "NOT_FOUND" in error_str or \
                     "invalid" in error_str.lower():
                    print(f"  ✗  [{model_name}] not available — skipping...")
                    break
                else:
                    print(f"  ✗  [{model_name}] error: {e}")
                    break
        print(f"  →  Moving to next model...")

    raise Exception(f"All models failed. Last error: {last_error}")


# ─────────────────────────────────────────────────────────────────────────────
#  Main Pipeline  — collects all data into a dict, then generates Word doc
# ─────────────────────────────────────────────────────────────────────────────

def run(pdf_path: str, question: str):

    print(f"\n{'='*60}")
    print(f"  RAG PIPELINE VISUALIZER")
    print(f"{'='*60}")
    print(f"  PDF      : {os.path.basename(pdf_path)}")
    print(f"  Question : {question}")
    print(f"{'='*60}\n")

    # ── Load embedding model ──────────────────────────────────────
    print("  [1/7]  Loading embedding model...")
    embed_model = SentenceTransformer(EMBED_MODEL_NAME)
    print(f"         Model: {EMBED_MODEL_NAME}  |  Dims: 384\n")

    # ── STEP 1: Extract text ──────────────────────────────────────
    print("  [2/7]  Extracting text from PDF...")
    raw_text = extract_text(pdf_path)
    print(f"         Extracted {len(raw_text.split())} words\n")

    # ── STEP 2: Chunk ─────────────────────────────────────────────
    print("  [3/7]  Chunking text...")
    chunks = chunk_text(raw_text, chunk_size=100, overlap=20)
    print(f"         Produced {len(chunks)} chunks\n")

    # ── STEP 3: Embed chunks ──────────────────────────────────────
    print("  [4/7]  Embedding chunks...")
    chunk_vectors = [embed_model.encode(c) for c in chunks]
    print(f"         Each chunk → 384-dim vector\n")

    # ── STEP 4: Embed question ────────────────────────────────────
    print("  [5/7]  Embedding question...")
    q_vec = embed_model.encode(question)
    print(f"         Question → 384-dim vector\n")

    # ── STEP 5: Cosine similarity with detailed breakdown ────────────
    print("  [6/7]  Computing cosine similarities with formula breakdown...")
    similarities = []
    similarity_details = []
    
    for i, (chunk, c_vec) in enumerate(zip(chunks, chunk_vectors)):
        sim = cosine_similarity(q_vec, c_vec)
        breakdown = calculate_similarity_breakdown(q_vec, c_vec)
        similarities.append((sim, i, chunk, c_vec.tolist()))
        similarity_details.append({
            "chunk_index": i + 1,
            "chunk_text": chunk[:100],
            "breakdown": breakdown
        })

    ranked = sorted(similarities, key=lambda x: x[0], reverse=True)
    top_k  = ranked[:TOP_K]
    print(f"         Top {TOP_K} chunks selected\n")

    # ── STEP 6: Call LLM ──────────────────────────────────────────
    print("  [7/7]  Calling LLM...")
    top_chunks = [r[2] for r in top_k]
    answer, used_model = call_llm(question, top_chunks)
    print()

    # ── Build data payload for Word doc generator ─────────────────
    data = {
        "pdf_name":      os.path.basename(pdf_path),
        "question":      question,
        "embed_model":   EMBED_MODEL_NAME,
        "llm_model":     used_model,
        "model_pool":    GEMINI_MODEL_POOL,
        "top_k":         TOP_K,
        "vector_dims":   384,
        "vector_preview": VECTOR_PREVIEW,

        # Step 1 — raw text sample
        "raw_text_words": len(raw_text.split()),
        "raw_text_sample": raw_text[:600],

        # Step 2 — all chunks
        "chunks": [
            {
                "index":      i + 1,
                "text":       chunk,
                "word_count": len(chunk.split()),
            }
            for i, chunk in enumerate(chunks)
        ],

        # Step 3 — chunk vectors
        "chunk_vectors": [
            {
                "chunk_index": i + 1,
                "preview":     cv[:VECTOR_PREVIEW],
                "norm":        float(np.linalg.norm(np.array(cv))),
            }
            for i, cv in enumerate([v.tolist() for v in chunk_vectors])
        ],

        # Step 4 — question vector
        "question_vector": {
            "preview": q_vec[:VECTOR_PREVIEW].tolist(),
            "norm":    float(np.linalg.norm(q_vec)),
        },

        # Step 5A — Vector comparison for each chunk (ENHANCED)
        "vector_comparisons": [
            {
                "chunk_index": detail["chunk_index"],
                "chunk_text": detail["chunk_text"],
                "question_vector_preview": q_vec[:VECTOR_PREVIEW].tolist(),
                "question_vector_norm": float(np.linalg.norm(q_vec)),
                "chunk_vector_preview": similarities[detail["chunk_index"] - 1][3][:VECTOR_PREVIEW],
                "chunk_vector_norm": float(np.linalg.norm(np.array(similarities[detail["chunk_index"] - 1][3]))),
            }
            for detail in similarity_details
        ],

        # Step 5B — Similarity calculation breakdown (ENHANCED)
        "similarity_calculations": [
            {
                "chunk_index": detail["chunk_index"],
                "dot_product": detail["breakdown"]["dot_product"],
                "question_norm": detail["breakdown"]["question_norm"],
                "chunk_norm": detail["breakdown"]["chunk_norm"],
                "formula": detail["breakdown"]["formula_breakdown"],
                "final_score": detail["breakdown"]["similarity_score"],
            }
            for detail in similarity_details
        ],

        # Step 5C — all similarities ranked
        "similarities_ranked": [
            {
                "rank":        rank + 1,
                "chunk_index": orig_idx + 1,
                "score":       round(sim, 4),
                "selected":    rank < TOP_K,
                "text":        chunk[:120],
            }
            for rank, (sim, orig_idx, chunk, _) in enumerate(ranked)
        ],

        # Step 6 — top-k chunks sent to LLM
        "top_k_chunks": [
            {
                "rank":        rank + 1,
                "chunk_index": orig_idx + 1,
                "score":       round(sim, 4),
                "text":        chunk,
                "vector_preview": c_vec[:VECTOR_PREVIEW],
                "norm":        float(np.linalg.norm(np.array(c_vec))),
            }
            for rank, (sim, orig_idx, chunk, c_vec) in enumerate(top_k)
        ],

        # Step 7 — answer
        "answer": answer,
    }

    # ── Save JSON for Node.js ─────────────────────────────────────
    report_dir = build_report_dir(pdf_path, question)
    os.makedirs(report_dir, exist_ok=True)
    json_path = os.path.join(report_dir, "rag_data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    rel_json_path = os.path.relpath(json_path, PROJECT_ROOT)
    print(f"  Pipeline data saved to {rel_json_path}")

    # ── Call Node.js to generate Word doc ─────────────────────────
    js_path   = os.path.join(PROJECT_ROOT, "scripts", "rag_report_gen.js")
    docx_path = os.path.join(report_dir, "rag_report.docx")

    print(f"  Generating Word document...")
    result = subprocess.run(
        ["node", js_path, json_path, docx_path],
        capture_output=True, text=True
    )

    if result.returncode == 0:
        rel_docx_path = os.path.relpath(docx_path, PROJECT_ROOT)
        print(f"\n{'='*60}")
        print(f"  ✓  Word document created:  {rel_docx_path}")
        print(f"{'='*60}\n")
    else:
        print(f"\n  [ERROR] Word generation failed:")
        print(result.stderr)

    # ── Cleanup JSON ──────────────────────────────────────────────
    if os.path.exists(json_path):
        os.remove(json_path)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("\n  Usage   :  python src/rag_visualizer.py \"path/to/paper.pdf\" \"your question\"")
        print("  Example :  python src/rag_visualizer.py \"papers/attention.pdf\" \"How does attention work?\"\n")
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

    run(pdf_path, question)
