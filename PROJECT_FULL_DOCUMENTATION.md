# AI Research Paper Assistant RAG - Full Documentation

This project extracts text from research papers, chunks the text, creates vector embeddings, retrieves the most relevant chunks for a question, and generates an answer using Gemini.

The main debug command now prints the RAG evidence directly in the terminal instead of generating a Word report.

```bash
python src/rag_answer_debug.py "papers/easy/cybersecurity_easy.pdf" "what should employees do"
```

Use complete vectors when needed:

```bash
python src/rag_answer_debug.py "papers/easy/cybersecurity_easy.pdf" "what should employees do" --full-vectors
```

## Output

The answer debug command prints:

1. PDF path and embedding model.
2. Extracted word count.
3. Total chunk count.
4. Question text and question vector.
5. Every chunk with its vector and similarity score.
6. Selected top-k chunks.
7. Final Gemini answer generated from the selected chunks.

By default, vectors are printed as previews so the terminal stays readable. `--full-vectors` prints all dimensions.

## Project Structure

```text
src/
  rag_answer_debug.py
  rag_visualizer.py
  analyze_pdf.py

pipeline/
  extractor.py
  chunker.py
  embedder.py
  retriever.py
  qa_engine.py
  pipeline.py
  difficulty_scorer.py
  model_config.py

docs/
  QUICK_START.md
  stepbystep.txt
  gitignore-template.txt

papers/
  easy/
  medium/
  hard/

assets/
chroma_db/
requirements.txt
README.md
command.txt
```

## Main Files

### `src/rag_answer_debug.py`

Runs the full terminal debug flow:

1. Loads `.env`.
2. Validates the PDF path and API key.
3. Extracts PDF text with `pipeline/extractor.py`.
4. Chunks text with `pipeline/chunker.py`.
5. Embeds chunks and the question with `BAAI/bge-base-en-v1.5`.
6. Computes cosine similarity between the question vector and every chunk vector.
7. Prints all chunks, vectors, scores, selected chunks, and the final answer.

Useful options:

```bash
--top-k 5
--preview-dims 20
--full-vectors
```

### `src/rag_visualizer.py`

Backward-compatible wrapper for `rag_answer_debug.py`. Existing commands using `rag_visualizer.py` still run the terminal debug flow.

### `pipeline/extractor.py`

Extracts PDF text. It first tries PyMuPDF and falls back to pdfplumber if very little text is found.

### `pipeline/chunker.py`

Splits extracted text into overlapping chunks using `RecursiveCharacterTextSplitter`.

### `pipeline/embedder.py`

Loads the `BAAI/bge-base-en-v1.5` embedding model and can store chunk vectors in ChromaDB for the interactive pipeline.

### `pipeline/retriever.py`

Retrieves relevant chunks from ChromaDB for the interactive Q&A pipeline.

### `pipeline/qa_engine.py`

Builds the answer prompt and calls Gemini using the shared fallback model pool from `model_config.py`.

### `pipeline/pipeline.py`

Runs the older interactive mode:

```bash
python pipeline/pipeline.py "papers/easy/cybersecurity_easy.pdf"
```

## Setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env`:

```text
GEMINI_API_KEY=your_api_key_here
```

## Verification

Compile the Python files:

```bash
python -m py_compile src/rag_answer_debug.py src/rag_visualizer.py src/analyze_pdf.py pipeline/pipeline.py pipeline/chunker.py pipeline/difficulty_scorer.py pipeline/embedder.py pipeline/extractor.py pipeline/model_config.py pipeline/qa_engine.py pipeline/retriever.py
```

Run a quick import check:

```bash
python -c "import pdfplumber, sentence_transformers, google.genai; print('All packages OK')"
```

## Notes

1. A valid Gemini API key is required for answer generation.
2. `chroma_db/` is generated automatically by the interactive pipeline.
3. The project uses a Python-only debug flow and does not generate Word reports.
