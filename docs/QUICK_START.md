# QUICK START - Copy & Paste Commands

## First Time Setup

```bash
# 1. Clone the project
git clone https://github.com/abdulsaboor85/AI-Research-Paper-Assistant-RAG.git
cd AI-Research-Paper-Assistant-RAG

# 2. Create virtual environment
python -m venv venv

# 3. Activate virtual environment
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# 4. Install Python packages
pip install -r requirements.txt

# 5. Create .env file with your API key
# Add this line:
# GEMINI_API_KEY=your_actual_key_from_aistudio.google.com
```

## Run RAG Answer Debug

```bash
python src/rag_answer_debug.py "papers/your_paper.pdf" "your question"
```

Example:

```bash
python src/rag_answer_debug.py "papers/easy/cybersecurity_easy.pdf" "what should employees do"
```

Output:

- The question and question vector
- Every chunk and its vector
- Similarity score for each chunk
- Selected chunks used for the answer
- Final answer generated from those selected chunks

To print every vector dimension instead of a short preview:

```bash
python src/rag_answer_debug.py "papers/easy/cybersecurity_easy.pdf" "what should employees do" --full-vectors
```

## Interactive Q&A

```bash
cd pipeline
python pipeline.py "../papers/easy/cybersecurity_easy.pdf"
```

Then type your questions. Type `exit` to quit.

## Dependencies

All runtime dependencies are Python packages installed from `requirements.txt`.

## File Structure

```text
AI-Research-Paper-Assistant-RAG/
src/
  rag_answer_debug.py     <- Main script for chunks, vectors, selected chunks, and answer
  analyze_pdf.py          <- Difficulty analyzer
docs/                     <- Guides and notes
assets/                   <- Images and visual assets
pipeline/                 <- RAG pipeline modules
papers/                   <- Put your PDF files here
chroma_db/                <- Auto-created vector database
requirements.txt          <- Install with: pip install -r requirements.txt
.env                      <- Create this and add: GEMINI_API_KEY=...
.gitignore                <- Prevents .env from being pushed
```

## Verification

```bash
python -c "import pdfplumber, sentence_transformers, google.genai; print('All packages OK')"
```

## Getting The API Key

1. Go to https://aistudio.google.com/app/apikey
2. Click "Create API Key"
3. Copy the key
4. Create `.env` with `GEMINI_API_KEY=your_copied_key`
