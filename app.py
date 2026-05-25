from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

# =========================================================
# PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

FRONTEND_DIR = BASE_DIR / "frontend"
PAPERS_DIR = BASE_DIR / "papers"
UPLOAD_DIR = PAPERS_DIR / "uploads"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

PIPELINE_DIR = BASE_DIR / "pipeline"

# IMPORTANT
sys.path.insert(0, str(PIPELINE_DIR))

# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)

# =========================================================
# HELPERS
# =========================================================


def to_relative_path(path: Path) -> str:
    return path.relative_to(BASE_DIR).as_posix()


def normalize_pdf_path(raw_path: str) -> Path:

    candidate = Path(raw_path.strip())

    if not candidate.is_absolute():
        candidate = (BASE_DIR / candidate).resolve()
    else:
        candidate = candidate.resolve()

    try:
        candidate.relative_to(BASE_DIR)

    except ValueError as exc:
        raise ValueError(
            "Path must stay inside the project directory."
        ) from exc

    if candidate.suffix.lower() != ".pdf":
        raise ValueError("File must be a PDF.")

    if not candidate.exists():
        raise FileNotFoundError(f"PDF not found: {raw_path}")

    return candidate


def collection_name_from_path(pdf_path: Path) -> str:

    relative = pdf_path.relative_to(BASE_DIR).as_posix().lower()

    safe = re.sub(r"[^a-z0-9]+", "_", relative).strip("_")

    return f"paper_{safe or 'default'}"


def paper_record(pdf_path: Path) -> dict[str, Any]:

    stat = pdf_path.stat()

    return {
        "id": to_relative_path(pdf_path),
        "title": pdf_path.stem,
        "filename": pdf_path.name,
        "path": to_relative_path(pdf_path),
        "collectionName": collection_name_from_path(pdf_path),
        "modifiedAt": datetime.fromtimestamp(
            stat.st_mtime
        ).isoformat(),
    }


def list_papers() -> list[dict[str, Any]]:

    pdf_files = sorted(
        {
            path.resolve()
            for path in PAPERS_DIR.rglob("*.pdf")
            if path.is_file()
        },
        key=lambda item: item.name.lower(),
    )

    return [paper_record(path) for path in pdf_files]


# =========================================================
# INDEXING
# =========================================================

def index_paper(pdf_path: Path, collection_name: str) -> None:

    from chunker import chunk_text
    from embedder import embed_and_store
    from extractor import extract_text

    full_text = extract_text(str(pdf_path))

    if len(full_text.strip()) < 100:
        raise ValueError("Could not extract enough text from PDF.")

    chunks = chunk_text(full_text)

    if not chunks:
        raise ValueError("Chunking produced no chunks.")

    embed_and_store(
        chunks,
        collection_name=collection_name
    )


# =========================================================
# ANALYZE PAPER
# =========================================================

def analyze_paper(
    pdf_path: Path,
    reindex: bool = True
) -> dict[str, Any]:

    from difficulty_scorer import analyze_difficulty
    from extractor import extract_text

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError("GEMINI_API_KEY missing in .env")

    collection_name = collection_name_from_path(pdf_path)

    full_text = extract_text(str(pdf_path))

    if len(full_text.strip()) < 100:
        raise ValueError("Could not extract enough text.")

    if reindex:
        index_paper(pdf_path, collection_name)

    result = analyze_difficulty(
        full_text=full_text,
        api_key=api_key
    )

    result["paper"] = paper_record(pdf_path)

    result["paper"]["collectionName"] = collection_name

    return result


# =========================================================
# RESOLVE COLLECTION
# =========================================================

def resolve_collection_name(data: dict[str, Any]) -> str:

    paper_path = (
        data.get("paper_path")
        or data.get("path")
        or data.get("paperPath")
    )

    if paper_path:
        return collection_name_from_path(
            normalize_pdf_path(str(paper_path))
        )

    active_id = (
        data.get("paper_id")
        or data.get("paperId")
    )

    if active_id:
        return collection_name_from_path(
            normalize_pdf_path(str(active_id))
        )

    raise ValueError("paper_path is required.")


# =========================================================
# STATIC ROUTES
# =========================================================

@app.get("/")
def index() -> Any:
    return send_from_directory(
        FRONTEND_DIR,
        "index.html"
    )


@app.get("/style.css")
def style() -> Any:
    return send_from_directory(
        FRONTEND_DIR,
        "style.css"
    )


@app.get("/script.js")
def script() -> Any:
    return send_from_directory(
        FRONTEND_DIR,
        "script.js"
    )


@app.get("/assets/<path:filename>")
def assets(filename: str) -> Any:
    return send_from_directory(
        BASE_DIR / "assets",
        filename
    )


@app.get("/uploads/<path:filename>")
def uploads(filename: str) -> Any:
    return send_from_directory(
        UPLOAD_DIR,
        filename
    )


# =========================================================
# API ROUTES
# =========================================================

@app.get("/api/papers")
def api_papers() -> Any:

    return jsonify({
        "papers": list_papers()
    })


# =========================================================
# UPLOAD
# =========================================================

@app.post("/api/upload")
def api_upload() -> Any:

    if "file" not in request.files:
        return jsonify({
            "error": "No file uploaded."
        }), 400

    uploaded = request.files["file"]

    if not uploaded.filename:
        return jsonify({
            "error": "Empty filename."
        }), 400

    if not uploaded.filename.lower().endswith(".pdf"):
        return jsonify({
            "error": "Only PDF files allowed."
        }), 400

    filename = secure_filename(uploaded.filename)

    stamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    saved_name = f"{stamp}_{filename}"

    saved_path = UPLOAD_DIR / saved_name

    uploaded.save(saved_path)

    try:

        analysis = analyze_paper(
            saved_path,
            reindex=True
        )

    except Exception:

        if saved_path.exists():
            saved_path.unlink()

        raise

    paper = analysis.pop("paper")

    return jsonify({
        "paper": paper,
        "analysis": analysis
    })


# =========================================================
# ANALYZE
# =========================================================

@app.post("/api/analyze")
def api_analyze() -> Any:

    data = request.get_json(silent=True) or {}

    raw_path = (
        data.get("paper_path")
        or data.get("path")
        or data.get("paperId")
    )

    if not raw_path:
        return jsonify({
            "error": "paper_path is required."
        }), 400

    try:

        pdf_path = normalize_pdf_path(
            str(raw_path)
        )

        analysis = analyze_paper(
            pdf_path,
            reindex=True
        )

        paper = analysis.pop("paper")

        return jsonify({
            "paper": paper,
            "analysis": analysis
        })

    except Exception as exc:

        return jsonify({
            "error": str(exc)
        }), 400


# =========================================================
# CHAT
# =========================================================

@app.post("/api/chat")
def api_chat() -> Any:

    from qa_engine import answer_question
    from retriever import retrieve_relevant_chunks

    data = request.get_json(silent=True) or {}

    question = (
        data.get("message")
        or data.get("question")
        or ""
    ).strip()

    if not question:
        return jsonify({
            "error": "message is required."
        }), 400

    try:

        collection_name = resolve_collection_name(data)

        chunks = retrieve_relevant_chunks(
            question,
            collection_name=collection_name
        )

        reply = answer_question(
            question,
            chunks
        )

        return jsonify({
            "reply": reply,
            "collectionName": collection_name,
            "chunksUsed": len(chunks),
        })

    except Exception as exc:

        return jsonify({
            "error": str(exc)
        }), 400


# =========================================================
# PREREQUISITES
# =========================================================

@app.post("/api/prerequisites")
def api_prerequisites():

    try:

        from prerequisite_extractor import (
            PrerequisiteExtractor,
            extract_pdf_text
        )

        data = request.get_json(silent=True) or {}

        raw_path = (
            data.get("paper_path")
            or data.get("path")
            or data.get("paperId")
        )

        if not raw_path:
            return jsonify({
                "error": "paper_path is required."
            }), 400

        pdf_path = normalize_pdf_path(
            str(raw_path)
        )

        text = extract_pdf_text(
            str(pdf_path)
        )

        if len(text.strip()) < 100:
            return jsonify({
                "error": "Could not extract enough text."
            }), 400

        extractor = PrerequisiteExtractor()

        result = extractor.extract(text)

        return jsonify({
            "prerequisites": result,
            "paper_path": str(raw_path),
        })

    except Exception as exc:

        print("\n❌ PREREQUISITE ERROR:")
        print(exc)

        import traceback
        traceback.print_exc()

        return jsonify({
            "error": str(exc)
        }), 400


# =========================================================
# TEST ROUTE
# =========================================================

@app.get("/hello")
def hello():
    return "HELLO WORKING"


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    print("\n🚀 Flask server starting...")
    print("📍 http://127.0.0.1:5000")
    print("📍 Test route: http://127.0.0.1:5000/hello\n")

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True,
        use_reloader=True
    )