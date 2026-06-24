# Paper Insight AI

An AI-powered research paper assistant built with Flask, RAG (Retrieval-Augmented Generation), and Google Gemini. Upload any research paper PDF and get an interactive workspace to chat with it, analyze its difficulty, extract prerequisite knowledge, and get plain-English explanations of any technical term — all grounded strictly in the paper's own content.

## Features

- **Chat / Q&A** — Ask questions about the paper and get grounded, hallucination-resistant answers using Gemini + RAG retrieval over the paper's content.
- **Difficulty Scorer** — A weighted difficulty score (1–10) combining readability (Flesch-Kincaid), uncommon word density, technical term density (KeyBERT), and an LLM-based difficulty judgment.
- **Prerequisites Extractor** — Generates a 12–15 topic learning roadmap (beginner → advanced) needed to understand the paper.
- **Term Explainer** — Explains any term in three layers: what the paper says about it, a simple plain-English explanation, and a real-world analogy.
- **PDF Viewer** — Built-in zoomable PDF viewer with fullscreen mode, powered by PDF.js.
- **Authentication** — Per-user accounts with isolated paper storage (SQLite + hashed passwords).
- **Persistent Caching** — Analysis, prerequisites, and chat history are cached to disk so results survive server restarts and aren't recomputed.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Flask (Python) |
| Embeddings | `BAAI/bge-base-en-v1.5` (Sentence-Transformers) |
| Vector Store | ChromaDB |
| Text Splitting | LangChain `RecursiveCharacterTextSplitter` (chunk size 300, overlap 50) |
| LLM | Google Gemini (model pool with automatic fallback) |
| Keyword Extraction | KeyBERT |
| PDF Extraction | PyMuPDF (primary), pdfplumber (fallback) |
| Auth / Storage | SQLite |
| Frontend | Vanilla HTML/CSS/JS, PDF.js |

## Project Structure