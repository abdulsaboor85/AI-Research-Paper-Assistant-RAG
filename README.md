# PaperInsight AI

A research-paper assistant for students. Upload a paper (PDF) and get a workspace to chat with it, check how hard it is, see what you should learn first, understand terms, and polish your own writing. Built with Flask, RAG (ChromaDB + Google Gemini) and a small fine-tuned writing model that runs on your own computer.

## Features

- **Chat / Q&A**: ask questions about the paper. Answers use only text retrieved from the paper (RAG), so they stay grounded.
- **Difficulty Score**: a 1 to 10 score from readability (Flesch-Kincaid), uncommon words, technical terms (KeyBERT) and a Gemini judgement.
- **Prerequisites Roadmap**: a 12 to 15 topic learning list, from beginner to advanced.
- **Term Explainer**: type a term, or select text in the PDF. You get what the paper says, a simple explanation, and a real-world example.
- **Memory (personalization)**: terms you have explained are saved. Known terms are removed from the Prerequisites list and lower the Difficulty Score.
- **PDF Viewer**: zoom, fullscreen, text selection.
- **Writing Mentor**: turns casual sentences or a short paragraph into formal academic English, using a fine-tuned model that runs offline in Ollama. The original is shown next to the rewrite, with "please check" warnings.
- **Accounts**: each user has their own papers, memory and Gemini API key (SQLite, salted password hashes).
- **Caching**: analysis, prerequisites, summaries and chat history are saved to disk.

The **Summary** and **Comparison** tabs are placeholders ("Coming Soon").

## Tech stack

| Part | Technology |
|---|---|
| Backend | Python 3.11, Flask |
| Embeddings | `BAAI/bge-base-en-v1.5` (Sentence-Transformers) |
| Vector store | ChromaDB |
| Text splitting | LangChain `RecursiveCharacterTextSplitter` |
| LLM | Google Gemini (model pool with fallback) |
| Keywords | KeyBERT |
| PDF reading | PyMuPDF (main), pdfplumber (fallback) |
| Writing Mentor | Fine-tuned Qwen3.5-2B (GGUF) served by Ollama |
| Database | SQLite |
| Frontend | Vanilla HTML, CSS, JavaScript, PDF.js |

## Project structure

```
app.py                  Flask routes (entry point)
auth_routes.py          Login, signup, logout
requirements.txt
pipeline/
  chunker.py            Split paper text into chunks
  database.py           Users, known terms, Gemini key (SQLite)
  difficulty_scorer.py  Difficulty score
  embedder.py           Embedding model and ChromaDB
  extractor.py          PDF text extraction
  model_config.py       Gemini helper with model fallback
  personalization.py    Use known terms to adjust results
  prerequisite_extractor.py
  qa_engine.py          Grounded Q&A prompt
  retriever.py          Find relevant chunks
  term_explainer.py     Explain a term
  writing_mentor.py     Writing Mentor routes, safety checks, Ollama call
  writing_checker.py    Meaning check for rewrites
frontend/
  index.html, script.js, style.css     Main app
  auth.html, auth.js, auth.css         Login page
papers/uploads/<user_id>/              Uploaded PDFs (created automatically)
cache/  chroma_db/  logs/              Created automatically
users.db  .secret_key                  Created automatically (keep private)
```

## Install and run (Windows)

1. Install **Python 3.11**.
2. Open cmd in the project folder (quote paths that contain spaces):
```
   cd /d "C:\path\to\AI-Research-Paper-Assistant-RAG"
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
```
3. **Download the embedding model once.** `embedder.py` forces offline mode, so the model must already be on your computer. Run this one time, with internet:
```
   python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-base-en-v1.5')"
```
4. Create a `.env` file in the project folder (optional):
```
   GEMINI_API_KEY=your_key_here
```
   You can also save a key per user inside the app (Settings, then Gemini API Key). Never share this file or your key.
5. Start the app:
```
   python app.py
```
   Open http://127.0.0.1:5000, create an account, and upload a PDF.

The first run also downloads small NLTK data files, so it needs internet once.

Optional settings: `SECRET_KEY` (otherwise a key is saved in `.secret_key`, so users stay logged in after a restart), `FLASK_DEBUG=1` (debug mode, off by default), `OLLAMA_URL`, `WRITING_MODEL`.

## Set up the Writing Mentor (Ollama)

The Writing Mentor needs Ollama and the `writing-mentor-v2` model. The other features work without it.

1. Install Ollama from https://ollama.com and start it. It listens on http://localhost:11434.
2. Put the model file (`writing-mentor-v2.Q4_K_M.gguf`) in a folder together with a file named `Modelfile_v2`. The GGUF file is large and is **not** included in this repository.
3. Contents of `Modelfile_v2`:
```
   FROM ./writing-mentor-v2.Q4_K_M.gguf
   TEMPLATE "{{ .Prompt }}"
   PARAMETER temperature 0
   PARAMETER stop "<|im_end|>"
```
   `TEMPLATE "{{ .Prompt }}"` is important. The app sends the full ChatML prompt itself (raw mode), exactly as the model was trained.
4. Create the model:
```
   cd /d "C:\path\to\folder with the gguf and Modelfile"
   ollama create writing-mentor-v2 -f Modelfile_v2
   ollama list
```
   `writing-mentor-v2` should appear in the list.
5. In the app, open the Writing Mentor tab. If Ollama is off or the model is missing, a message tells you.

### How the Writing Mentor works

- The model was trained on **one sentence at a time**, so a paragraph is split into sentences, each sentence is rewritten separately, and the results are joined back in your original layout.
- Limits: 2000 characters and 12 sentences per request.
- The model has no safety training. All safety is outside it: input checks (threats, self-harm, illegal "how to" requests), quoted text is hidden from the model and restored unchanged, the output is checked again, a rate limit (20 requests per minute per user), a pause after 5 blocked attempts in 10 minutes, and a log in `logs/blocked_rewrites.jsonl`.
- A meaning check compares each rewrite with the original: numbers, abbreviations, negation, many new words, comparison direction, and embedding similarity. Problems show as "Please check".

## Known limits

- **The model makes mistakes.** It sometimes flips "lower is better" comparisons (error rate, latency) and sometimes swaps simple words for fancier ones. That is why the original is shown next to the rewrite, with warnings. Always read the result.
- **The safety rules are simple.** They catch obvious threats only. There is no slur list. Clever or hidden wording can get through.
- The meaning check is a helper, not a guarantee. It can warn when nothing is wrong, and miss real problems.
- Scanned PDFs without text are not supported (no OCR).
- Chat, difficulty, prerequisites and explainers need internet and a Gemini key. The Writing Mentor works offline.
- The first Writing Mentor request can be slow while Ollama loads the model.
- Gemini keys are stored in `users.db` as plain text. Keep that file private.
- Rate limits are kept in memory and reset when the server restarts.
- This is a student project run with the Flask development server. It is not hardened for public internet use.