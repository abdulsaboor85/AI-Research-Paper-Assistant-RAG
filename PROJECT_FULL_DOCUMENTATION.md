# AI Research Paper Assistant RAG - Full Project Documentation

This file explains the whole working of the project, its features, folder structure, execution flow, and every function found in the source code.

## 1. Project Overview

AI Research Paper Assistant RAG is a Retrieval-Augmented Generation project for working with research papers in PDF format.

The system can:

1. Extract text from a research paper PDF.
2. Split the paper into smaller chunks.
3. Convert chunks into vector embeddings.
4. Retrieve the chunks most relevant to a user question.
5. Send the retrieved context to Gemini.
6. Generate an answer grounded in the paper.
7. Generate a Word report that visualizes the RAG pipeline step by step.
8. Analyze the difficulty level of a paper using readability, vocabulary, technical terms, and LLM judgment.

The project has two main usage modes:

1. Full visual RAG report:

```bash
python src/rag_visualizer.py "papers/easy/cybersecurity_easy.pdf" "what should employees do"
```

This creates a Word report under:

```text
reports/<paper-name>__<question>/rag_report.docx
```

2. Interactive RAG Q&A:

```bash
python pipeline/pipeline.py "papers/easy/cybersecurity_easy.pdf"
```

This processes the PDF once, then lets the user ask multiple questions in the terminal.

3. Difficulty analysis:

```bash
python src/analyze_pdf.py "papers/easy/cybersecurity_easy.pdf"
```

This prints a difficulty score and component breakdown.

## 2. Main Features

### PDF Text Extraction

The project extracts text from PDFs using PyMuPDF or pdfplumber depending on the script. The visualizer uses pdfplumber word extraction so words are reconstructed with proper spacing.

### Text Chunking

The extracted paper text is split into smaller chunks. Chunking makes retrieval easier because the system searches short passages instead of the whole paper at once.

### Embeddings

The project uses SentenceTransformer models to convert text chunks and questions into numerical vectors.

Models used:

```text
BAAI/bge-base-en-v1.5
all-MiniLM-L6-v2
```

### Vector Storage

The interactive pipeline stores chunk embeddings in ChromaDB. ChromaDB is persisted in the `chroma_db/` folder.

### Retrieval

When the user asks a question, the system embeds the question and retrieves the most relevant chunks. For summary questions, retrieval is adjusted to prefer abstract, introduction, conclusion, results, and contribution-like chunks while filtering references and low-signal chunks.

### Gemini Answer Generation

The selected chunks are sent to Gemini with a prompt that tells the model to answer only from the provided paper context.

### Gemini Model Fallback Pool

The project uses a shared Gemini model pool:

```text
gemini-3.1-flash-lite
gemini-2.5-flash
gemini-3-flash
gemini-2.5-flash-lite
```

If one model fails, is unavailable, invalid, or quota-limited, the code retries or moves to the next model.

### RAG Visualization Report

The visualizer produces a `.docx` report showing:

1. PDF text extraction.
2. Text chunks.
3. Chunk embeddings.
4. Question embedding.
5. Vector comparison.
6. Cosine similarity calculations.
7. Similarity ranking.
8. Top retrieved chunks.
9. Final LLM answer.

### Difficulty Analysis

The difficulty analyzer scores a paper using:

1. Readability score.
2. Uncommon word score.
3. Technical term score.
4. LLM perception score.

The final score is weighted mostly toward LLM perception:

```text
readability: 10%
uncommon words: 10%
technical terms: 10%
LLM perception: 70%
```

## 3. Project Structure

```text
src/
  analyze_pdf.py
  rag_visualizer.py

pipeline/
  chunker.py
  difficulty_scorer.py
  embedder.py
  extractor.py
  model_config.py
  pipeline.py
  qa_engine.py
  retriever.py

scripts/
  rag_report_gen.js

docs/
  QUICK_START.md
  gitignore-template.txt
  stepbystep.txt

papers/
  easy/
  medium/
  hard/

reports/
  generated Word reports

assets/
  image and visual assets

chroma_db/
  auto-generated ChromaDB vector database
```

## 4. Important Configuration Files

### `.env`

Contains the Gemini API key:

```text
GEMINI_API_KEY=your_api_key_here
```

This file should not be committed to Git.

### `requirements.txt`

Python dependencies:

```text
pdfplumber
python-dotenv
sentence-transformers
numpy
chromadb
google-genai
nltk
spacy
wordfreq
en_core_sci_sm
```

### `package.json`

Node dependency:

```text
docx
```

The `docx` package is used to generate Word reports.

## 5. Full Working Flow

### Flow A: Visual RAG Report

File:

```text
src/rag_visualizer.py
```

Working:

1. User runs the script with a PDF path and question.
2. The script checks that the PDF exists, is a `.pdf`, and `GEMINI_API_KEY` exists.
3. It loads the embedding model `all-MiniLM-L6-v2`.
4. It extracts text from the PDF using pdfplumber word extraction.
5. It chunks the text into 100-word chunks with 20-word overlap.
6. It embeds every chunk into a 384-dimensional vector.
7. It embeds the user question into a vector.
8. It calculates cosine similarity between the question vector and every chunk vector.
9. It ranks chunks by similarity.
10. It selects the top 3 chunks.
11. It calls Gemini using the shared model fallback pool.
12. It builds a JSON payload containing all pipeline details.
13. It calls `scripts/rag_report_gen.js`.
14. The JavaScript script generates a Word report.
15. Temporary JSON is deleted.

### Flow B: Interactive RAG Q&A

File:

```text
pipeline/pipeline.py
```

Working:

1. User runs the script with a PDF path.
2. `extractor.py` extracts PDF text.
3. `chunker.py` splits text into chunks.
4. `embedder.py` embeds chunks and stores them in ChromaDB.
5. User enters a question.
6. `retriever.py` retrieves relevant chunks from ChromaDB.
7. `qa_engine.py` sends retrieved chunks and question to Gemini.
8. The answer is printed.
9. User can continue asking questions until typing `exit`.

### Flow C: Difficulty Analysis

File:

```text
src/analyze_pdf.py
```

Working:

1. User runs the script with a PDF path.
2. The script validates the file and API key.
3. It extracts text with pdfplumber.
4. It calls `analyze_difficulty()` from `pipeline/difficulty_scorer.py`.
5. The difficulty scorer computes readability, uncommon words, technical terms, and LLM perception.
6. It combines the component scores into a final score.
7. It prints the difficulty label and paper statistics.

## 6. Function-by-Function Explanation

## `pipeline/extractor.py`

### `extract_text_pymupdf(pdf_path)`

Opens a PDF using PyMuPDF, loops through every page, extracts text with `page.get_text()`, closes the document, and returns the combined text.

### `extract_text_pdfplumber(pdf_path)`

Opens a PDF using pdfplumber, loops through each page, extracts text with `page.extract_text()`, appends available page text, and returns the combined text.

### `extract_text(pdf_path)`

Main extractor function for the interactive pipeline. It first tries PyMuPDF. If the extracted text is too short, it falls back to pdfplumber. It returns cleaned text.

## `pipeline/chunker.py`

### `chunk_text(text)`

Splits text into chunks using LangChain `RecursiveCharacterTextSplitter`.

Settings:

```text
chunk_size = 800 characters
chunk_overlap = 150 characters
separators = blank lines, new lines, spaces
```

It returns a list of chunks.

## `pipeline/embedder.py`

### `get_or_create_collection(collection_name="research_papers")`

Gets an existing ChromaDB collection or creates it if it does not exist.

### `embed_and_store(chunks, collection_name="research_papers_v2")`

Deletes the existing collection with the same name, creates a fresh collection, embeds all chunks using `BAAI/bge-base-en-v1.5`, creates chunk IDs and metadata, stores documents and embeddings in ChromaDB, prints the number of stored chunks, and returns the collection.

## `pipeline/retriever.py`

### `_is_summary_question(query)`

Checks whether the query looks like a summary-style question. It searches for phrases like `summarize`, `summary`, `main idea`, `objective`, and `what is this paper about`.

### `_low_signal_score(chunk)`

Scores a chunk for low-value content. It increases the score when the chunk looks like references, bibliography, proceedings, DOI text, figures, tables, too many years, too many digits, or repeated words.

### `_high_signal_score(chunk)`

Scores a chunk for useful research-paper content. It looks for terms like abstract, introduction, conclusion, we propose, experiments, results, and contributions.

### `_get_opening_chunks(collection, count=3)`

Fetches the first few chunks from ChromaDB by IDs like `chunk_0`, `chunk_1`, and `chunk_2`. This helps summary questions include opening paper context.

### `_dedupe(chunks)`

Removes duplicate chunks by normalizing whitespace and comparing the first 500 characters of each chunk.

### `retrieve_relevant_chunks(query, collection_name="research_papers_v2", top_k=10)`

Main retrieval function. It embeds the query, queries ChromaDB, ranks candidate chunks, adjusts ranking for summary questions, filters low-signal chunks, adds opening chunks for summary questions, removes duplicates, and returns the final selected chunks.

## `pipeline/qa_engine.py`

### `answer_question(question, context_chunks)`

Joins retrieved chunks into one context, builds a prompt for Gemini, and asks the model to answer using only the provided context. It tries each model from `GEMINI_MODEL_POOL`, retries quota or service errors, skips invalid models, and returns the answer text. If all models fail, it raises an exception.

## `pipeline/model_config.py`

This file has no functions. It defines shared constants:

### `GEMINI_MODEL_POOL`

List of Gemini models tried in order.

### `MODEL_METADATA`

Stores RPM, TPM, RPD, and type information for each configured Gemini model.

### `MAX_RETRIES_PER_MODEL`

Number of retries before moving to the next model.

### `RETRY_DELAY_SECONDS`

Delay between retry attempts.

## `pipeline/pipeline.py`

### `process_pdf(pdf_path)`

Runs the PDF processing stage for interactive Q&A. It extracts text, chunks it, embeds chunks, stores them in ChromaDB, and prints progress messages.

### `ask(question)`

Retrieves relevant chunks for a question, sends them to `answer_question()`, and returns the generated answer.

### Main terminal loop

When the file is run directly, it expects a PDF path. It processes the PDF, then repeatedly asks for user questions until the user types `exit`.

## `pipeline/difficulty_scorer.py`

### `_count_syllables(word)`

Heuristic syllable counter. It counts vowel groups, subtracts a silent trailing `e`, and returns at least 1 syllable.

### `compute_readability_score(text)`

Computes:

1. Flesch-Kincaid Grade Level normalized to 0-10.
2. Flesch Reading Ease score from 0-100.

It tokenizes sentences and words, calculates average sentence length and average syllables per word, then returns both scores.

### `compute_uncommon_word_score(text)`

Uses `wordfreq` to count words whose real-world English frequency is below `UNCOMMON_FREQ_THRESHOLD`. It converts the uncommon-word ratio into a 0-10 score.

### `compute_technical_term_score(text)`

Uses scispaCy `en_core_sci_sm` to detect scientific entities. It filters detected entity tokens against NLTK common English words so normal words are not overcounted. It returns a 0-10 technical density score.

### `compute_llm_score(opening_text, api_key)`

Sends the paper opening to Gemini and asks for a difficulty score from 1 to 10. It uses the shared Gemini model pool with retry and fallback behavior. If all models fail, it returns fallback score `5`.

### `extract_opening_text(full_text)`

Extracts the most useful opening text for LLM scoring. It looks for Abstract and Introduction headings. If headings are not found, it uses the first 3000 characters.

### `analyze_difficulty(full_text, api_key)`

Main difficulty-analysis function. It extracts opening text, computes all component scores, calculates the weighted final score, assigns a difficulty label, computes paper statistics, and returns a dictionary containing scores, weights, final score, label, and breakdown.

## `src/analyze_pdf.py`

### `extract_text_from_pdf(pdf_path)`

Extracts all text from a PDF using pdfplumber and returns cleaned text.

### `print_result(result, pdf_path)`

Prints a formatted terminal report containing final difficulty score, label, component scores, total sentences, total words, uncommon word percentage, and technical term percentage.

### `main()`

Validates command-line input, checks file existence, checks `.pdf` extension, checks `GEMINI_API_KEY`, extracts PDF text, verifies enough text was extracted, calls `analyze_difficulty()`, and prints the result.

## `src/rag_visualizer.py`

### `safe_folder_name(value, max_length=80)`

Converts a string into a safe folder name by replacing non-alphanumeric characters with underscores, trimming underscores, converting to lowercase, and limiting length.

### `build_report_dir(pdf_path, question)`

Builds a report output folder name from the paper name and question. If the folder already exists, it appends a timestamp to avoid overwriting old reports.

### `extract_text(pdf_path)`

Extracts PDF text using pdfplumber word-level extraction. It groups words into lines using their y-position and sorts words left-to-right so spacing is preserved.

### `chunk_text(text, chunk_size=100, overlap=20)`

Splits text into word-based chunks. Each chunk has up to 100 words, with 20 words overlapping between consecutive chunks.

### `cosine_similarity(a, b)`

Computes cosine similarity between two vectors:

```text
dot(a, b) / (norm(a) * norm(b))
```

It returns a float similarity score.

### `calculate_similarity_breakdown(question_vec, chunk_vec)`

Calculates dot product, question vector norm, chunk vector norm, cosine similarity, and a formula string. This is used in the Word report to show how similarity was computed.

### `call_llm(question, top_chunks)`

Builds a context from the top chunks and asks Gemini to answer the question only from that context. It tries models from the shared pool, retries quota and service errors, skips unavailable models, and returns a tuple:

```text
(answer_text, used_model_name)
```

### `run(pdf_path, question)`

Main visualizer pipeline. It loads the embedding model, extracts text, chunks text, embeds chunks, embeds the question, calculates similarities, selects top chunks, calls Gemini, builds the report data payload, saves temporary JSON, calls the Node.js report generator, and deletes the temporary JSON file.

### Main entry point

When run directly, the script validates arguments, checks the PDF path, checks the file extension, verifies `GEMINI_API_KEY`, and calls `run()`.

## `scripts/rag_report_gen.js`

### `generateReport(jsonPath, docxPath)`

Reads RAG pipeline data from JSON and creates a `.docx` report using the Node `docx` package.

The report includes:

1. Title page.
2. PDF name, question, embedding model, and LLM model.
3. PDF text extraction section.
4. Text chunking table.
5. Chunk embedding previews.
6. Question embedding preview.
7. Question-vs-chunk vector comparison.
8. Cosine similarity calculations.
9. Similarity ranking table.
10. Retrieved top chunks.
11. Final LLM answer.

It writes the final Word file to `docxPath`.

### JavaScript entry point

Reads command-line arguments:

```text
node rag_report_gen.js <json_path> <docx_path>
```

If either argument is missing, it prints usage and exits. Otherwise, it calls `generateReport()`.

## 7. Files and Their Purpose

### `README.md`

Short overview of the project structure and common commands.

### `command.txt`

Command reference for setup, dependency installation, running reports, running difficulty analysis, running interactive Q&A, and useful checks.

### `docs/QUICK_START.md`

Detailed setup and usage guide.

### `docs/stepbystep.txt`

Very short setup command notes.

### `docs/gitignore-template.txt`

Recommended `.gitignore` template including `.env`, virtual environments, caches, generated reports, ChromaDB, and editor files.

### `.gitignore`

Current Git ignore file. It ignores virtual environments, caches, ChromaDB, `.env`, and pipeline cache.

### `assets/image.png`

Image asset used by the project or documentation.

### `papers/`

Contains sample PDFs grouped by difficulty:

```text
easy/
medium/
hard/
```

### `reports/`

Contains generated Word reports.

### `chroma_db/`

Auto-generated persistent vector database used by ChromaDB.

## 8. Setup Commands

Create and activate virtual environment:

```bash
python -m venv venv
venv\Scripts\activate
```

Install Python dependencies:

```bash
python -m pip install -r requirements.txt
```

Install Node dependencies:

```bash
npm install
```

Create `.env` in project root:

```text
GEMINI_API_KEY=your_api_key_here
```

## 9. Run Commands

Full visual report:

```bash
python src/rag_visualizer.py "papers/easy/cybersecurity_easy.pdf" "what should employees do"
```

Difficulty analysis:

```bash
python src/analyze_pdf.py "papers/easy/cybersecurity_easy.pdf"
```

Interactive Q&A:

```bash
python pipeline/pipeline.py "papers/easy/cybersecurity_easy.pdf"
```

Check Node report generator syntax:

```bash
node --check scripts/rag_report_gen.js
```

Check Python syntax:

```bash
python -m py_compile src/rag_visualizer.py src/analyze_pdf.py pipeline/pipeline.py pipeline/chunker.py pipeline/difficulty_scorer.py pipeline/embedder.py pipeline/extractor.py pipeline/model_config.py pipeline/qa_engine.py pipeline/retriever.py
```

## 10. Important Notes

1. The project needs a valid Gemini API key in `.env`.
2. `chroma_db/` is generated automatically and should not be edited manually.
3. `reports/` contains generated output files.
4. The visualizer uses in-memory vectors and creates a Word document.
5. The interactive pipeline uses ChromaDB for persistent retrieval.
6. The difficulty analyzer needs NLTK data, spaCy, wordfreq, and the scispaCy model `en_core_sci_sm`.
7. Some comments in existing files appear with broken character encoding, but the code logic is still readable.

## 11. Short Final Summary

This project is a research-paper assistant that combines PDF processing, embeddings, vector retrieval, Gemini-based question answering, Word report generation, and paper difficulty scoring. It helps users understand research papers, ask grounded questions, inspect how RAG works internally, and measure how difficult a paper is to read.
