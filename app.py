import json
import os
import re
import secrets
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, request, send_from_directory, session
from werkzeug.utils import secure_filename

# =========================================================
# PATHS
# =========================================================

BASE_DIR     = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
PAPERS_DIR   = BASE_DIR / "papers"
UPLOAD_DIR   = PAPERS_DIR / "uploads"
CACHE_DIR    = BASE_DIR / "cache"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

PIPELINE_DIR = BASE_DIR / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from auth_routes import auth_bp

# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)

app.secret_key                        = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

app.register_blueprint(auth_bp)

# =========================================================
# PRE-LOAD HEAVY MODELS AT STARTUP
# =========================================================
print("[startup] Pre-loading embedding model...")
from embedder import model as _embed_model, client as _chroma_client
print("[startup] Embedding model ready.")

# =========================================================
# IN-MEMORY CACHES  (keyed by collection_name)
# =========================================================

_index_status:   dict[str, dict] = {}
_index_lock      = threading.Lock()

_analysis_cache: dict[str, dict] = {}
_analysis_lock   = threading.Lock()

_prereq_cache:   dict[str, str]  = {}
_prereq_lock     = threading.Lock()

_chat_cache:     dict[str, list] = {}
_chat_lock       = threading.Lock()


def _default_status() -> dict:
    return {"status": "ready", "step": "", "pct": 100, "message": ""}

def set_index_status(collection_name: str, status: str, step: str = "",
                     pct: int = 0, message: str = "") -> None:
    with _index_lock:
        _index_status[collection_name] = {
            "status": status, "step": step, "pct": pct, "message": message,
        }

def get_index_status(collection_name: str) -> dict:
    with _index_lock:
        return _index_status.get(collection_name, _default_status())


# =========================================================
# DISK-PERSISTENT CACHE HELPERS
# =========================================================

def _cache_file_path(collection_name: str, cache_type: str) -> Path:
    """Generate a safe file path for a given collection + cache type."""
    safe = re.sub(r"[^a-z0-9_]", "", collection_name.lower())
    return CACHE_DIR / f"{safe}_{cache_type}.json"


def get_cached_analysis(collection_name: str) -> dict | None:
    with _analysis_lock:
        # 1. Check RAM first
        if collection_name in _analysis_cache:
            return _analysis_cache[collection_name]
        # 2. Try disk
        path = _cache_file_path(collection_name, "analysis")
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                _analysis_cache[collection_name] = data   # warm RAM cache
                print(f"[cache] Loaded analysis from disk for {collection_name}")
                return data
            except Exception as e:
                print(f"[cache] Failed to read analysis cache: {e}")
        return None


def set_cached_analysis(collection_name: str, result: dict) -> None:
    with _analysis_lock:
        _analysis_cache[collection_name] = result
        path = _cache_file_path(collection_name, "analysis")
        try:
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[cache] Saved analysis to disk for {collection_name}")
        except Exception as e:
            print(f"[cache] Failed to write analysis cache: {e}")


def get_cached_prereqs(collection_name: str) -> str | None:
    with _prereq_lock:
        # 1. Check RAM first
        if collection_name in _prereq_cache:
            return _prereq_cache[collection_name]
        # 2. Try disk
        path = _cache_file_path(collection_name, "prereqs")
        if path.exists():
            try:
                data = path.read_text(encoding="utf-8")
                _prereq_cache[collection_name] = data    # warm RAM cache
                print(f"[cache] Loaded prereqs from disk for {collection_name}")
                return data
            except Exception as e:
                print(f"[cache] Failed to read prereqs cache: {e}")
        return None


def set_cached_prereqs(collection_name: str, result: str) -> None:
    with _prereq_lock:
        _prereq_cache[collection_name] = result
        path = _cache_file_path(collection_name, "prereqs")
        try:
            path.write_text(result, encoding="utf-8")
            print(f"[cache] Saved prereqs to disk for {collection_name}")
        except Exception as e:
            print(f"[cache] Failed to write prereqs cache: {e}")


# =========================================================
# CHAT HISTORY  (disk-persistent, per paper/collection)
# =========================================================

def get_cached_chat(collection_name: str) -> list:
    """Returns the stored chat history list for a paper, or [] if none."""
    with _chat_lock:
        if collection_name in _chat_cache:
            return _chat_cache[collection_name]
        path = _cache_file_path(collection_name, "chat")
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                _chat_cache[collection_name] = data
                print(f"[cache] Loaded chat history from disk for {collection_name}")
                return data
            except Exception as e:
                print(f"[cache] Failed to read chat cache: {e}")
        _chat_cache[collection_name] = []
        return []


def append_chat_messages(collection_name: str, user_text: str, reply_text: str) -> None:
    """Appends a user+assistant pair to the chat history and writes it to disk."""
    with _chat_lock:
        history = _chat_cache.get(collection_name)
        if history is None:
            path = _cache_file_path(collection_name, "chat")
            if path.exists():
                try:
                    history = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    history = []
            else:
                history = []

        history.append({"role": "user", "text": user_text})
        history.append({"role": "assistant", "text": reply_text})
        _chat_cache[collection_name] = history

        path = _cache_file_path(collection_name, "chat")
        try:
            path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[cache] Saved chat history to disk for {collection_name}")
        except Exception as e:
            print(f"[cache] Failed to write chat cache: {e}")


def clear_cached_chat(collection_name: str) -> None:
    with _chat_lock:
        _chat_cache[collection_name] = []
        path = _cache_file_path(collection_name, "chat")
        try:
            if path.exists():
                path.unlink()
        except Exception as e:
            print(f"[cache] Failed to delete chat cache: {e}")


# =========================================================
# HELPERS
# =========================================================

def get_user_upload_dir() -> Path:
    user_id  = session.get("user_id", "anonymous")
    user_dir = UPLOAD_DIR / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


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
        raise ValueError("Path must stay inside the project directory.") from exc
    if candidate.suffix.lower() != ".pdf":
        raise ValueError("File must be a PDF.")
    if not candidate.exists():
        raise FileNotFoundError(f"PDF not found: {raw_path}")
    return candidate


def collection_name_from_path(pdf_path: Path) -> str:
    """
    Generate a stable collection name from the PDF filename.

    FIX: Strips the timestamp prefix (YYYYMMDD_HHMMSS_) before hashing
    so the same paper uploaded twice gets the SAME collection name,
    preventing redundant re-embedding.

    Per-user isolation is preserved because the user upload dir
    is still part of the relative path used here.
    """
    # Use the relative path for user isolation, but strip timestamp from stem
    relative_dir  = pdf_path.parent.relative_to(BASE_DIR).as_posix().lower()
    stem          = pdf_path.stem.lower()
    stem          = re.sub(r"^\d{8}_\d{6}_", "", stem)   # strip timestamp prefix
    combined      = f"{relative_dir}/{stem}"
    safe          = re.sub(r"[^a-z0-9]+", "_", combined).strip("_")
    return f"paper_{safe or 'default'}"


def paper_record(pdf_path: Path) -> dict[str, Any]:
    stat        = pdf_path.stat()
    raw_stem    = pdf_path.stem
    clean_title = re.sub(r"^\d{8}_\d{6}_", "", raw_stem)
    cname       = collection_name_from_path(pdf_path)
    idx         = get_index_status(cname)

    return {
        "id":             to_relative_path(pdf_path),
        "title":          clean_title,
        "filename":       clean_title,
        "path":           to_relative_path(pdf_path),
        "collectionName": cname,
        "modifiedAt":     datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "indexStatus":    idx["status"],
        "indexPct":       idx["pct"],
        "indexStep":      idx["step"],
        "indexMessage":   idx["message"],
    }


def list_papers() -> list[dict[str, Any]]:
    user_dir  = get_user_upload_dir()
    pdf_files = sorted(
        {path.resolve() for path in user_dir.rglob("*.pdf") if path.is_file()},
        key=lambda p: p.name.lower(),
    )
    return [paper_record(path) for path in pdf_files]


# =========================================================
# INDEXING
# =========================================================

def index_paper_background(pdf_path: Path, collection_name: str) -> None:
    """
    Background indexing. Uses pre-loaded model singleton.
    Steps: extract (0-20%) -> chunk (20-40%) -> embed (40-95%) -> done (100%)

    FIX: collection_exists_and_has_data() now correctly hits the same
    collection for the same paper (timestamp stripped from name),
    so re-uploads skip embedding entirely.
    """
    set_index_status(collection_name, "indexing", "Starting...", 5, "Preparing to index")

    def _run() -> None:
        try:
            from chunker  import chunk_text
            from embedder import embed_and_store, collection_exists_and_has_data
            from extractor import extract_text

            # If already indexed (same paper uploaded before), skip everything
            if collection_exists_and_has_data(collection_name):
                set_index_status(collection_name, "ready", "Done", 100, "Ready (cached)")
                print(f"[indexer] {collection_name} already indexed - skipping embed.")
                return

            set_index_status(collection_name, "indexing", "Extracting text", 15, "Reading PDF text...")
            full_text = extract_text(str(pdf_path))
            if len(full_text.strip()) < 100:
                raise ValueError("Could not extract enough text from PDF.")

            set_index_status(collection_name, "indexing", "Chunking", 35, "Splitting into chunks...")
            chunks = chunk_text(full_text)
            if not chunks:
                raise ValueError("Chunking produced no chunks.")

            set_index_status(collection_name, "indexing", "Embedding", 55, f"Embedding {len(chunks)} chunks...")
            embed_and_store(chunks, collection_name=collection_name, force=False)

            set_index_status(collection_name, "ready", "Done", 100, "Ready")
            print(f"[indexer] {collection_name} ready.")

        except Exception as exc:
            set_index_status(collection_name, "error", "Failed", 0, str(exc))
            print(f"[indexer] {collection_name} failed: {exc}")

    threading.Thread(target=_run, daemon=True).start()


# =========================================================
# ANALYZE PAPER  (cached — only runs Gemini once per paper)
# =========================================================

def analyze_paper(pdf_path: Path) -> dict[str, Any]:
    from difficulty_scorer import analyze_difficulty
    from extractor         import extract_text

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY missing in .env")

    collection_name = collection_name_from_path(pdf_path)

    cached = get_cached_analysis(collection_name)
    if cached:
        print(f"[analyze] Returning cached analysis for {collection_name}")
        return cached

    full_text = extract_text(str(pdf_path))
    if len(full_text.strip()) < 100:
        raise ValueError("Could not extract enough text.")

    result = analyze_difficulty(full_text=full_text, api_key=api_key)
    result["paper"]                   = paper_record(pdf_path)
    result["paper"]["collectionName"] = collection_name

    set_cached_analysis(collection_name, result)
    return result


# =========================================================
# RESOLVE COLLECTION
# =========================================================

def resolve_collection_name(data: dict[str, Any]) -> str:
    paper_path = (data.get("paper_path") or data.get("path") or data.get("paperPath"))
    if paper_path:
        return collection_name_from_path(normalize_pdf_path(str(paper_path)))
    active_id = (data.get("paper_id") or data.get("paperId"))
    if active_id:
        return collection_name_from_path(normalize_pdf_path(str(active_id)))
    raise ValueError("paper_path is required.")


# =========================================================
# STATIC ROUTES
# =========================================================

@app.get("/")
def index() -> Any:
    if "user_id" not in session:
        return redirect("/auth")
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.get("/style.css")
def style() -> Any:
    return send_from_directory(FRONTEND_DIR, "style.css")

@app.get("/script.js")
def script() -> Any:
    return send_from_directory(FRONTEND_DIR, "script.js")

@app.get("/assets/<path:filename>")
def assets(filename: str) -> Any:
    return send_from_directory(BASE_DIR / "assets", filename)

@app.get("/uploads/<path:filename>")
def uploads(filename: str) -> Any:
    return send_from_directory(UPLOAD_DIR, filename)


# =========================================================
# API — PAPERS LIST
# =========================================================

@app.get("/api/papers")
def api_papers() -> Any:
    if "user_id" not in session:
        return jsonify({"error": "Not logged in."}), 401
    return jsonify({"papers": list_papers()})


# =========================================================
# API — INDEXING STATUS
# =========================================================

@app.get("/api/status/<path:paper_path>")
def api_status(paper_path: str) -> Any:
    if "user_id" not in session:
        return jsonify({"error": "Not logged in."}), 401
    try:
        pdf_path        = normalize_pdf_path(paper_path)
        collection_name = collection_name_from_path(pdf_path)
        info            = get_index_status(collection_name)
        return jsonify({
            "status": info["status"], "step": info["step"],
            "pct": info["pct"], "message": info["message"],
            "collectionName": collection_name,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


# =========================================================
# API — UPLOAD
# =========================================================

@app.post("/api/upload")
def api_upload() -> Any:
    if "user_id" not in session:
        return jsonify({"error": "Not logged in."}), 401
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"error": "Empty filename."}), 400
    if not uploaded.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files allowed."}), 400

    filename   = secure_filename(uploaded.filename)
    stamp      = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved_name = f"{stamp}_{filename}"
    saved_path = get_user_upload_dir() / saved_name
    uploaded.save(saved_path)

    collection_name = collection_name_from_path(saved_path)
    index_paper_background(saved_path, collection_name)

    return jsonify({"paper": paper_record(saved_path), "analysis": {}})


# =========================================================
# API — ANALYZE  (cached after first run)
# =========================================================

@app.post("/api/analyze")
def api_analyze() -> Any:
    if "user_id" not in session:
        return jsonify({"error": "Not logged in."}), 401

    data = request.get_json(silent=True) or {}
    raw_path = (data.get("paper_path") or data.get("path") or data.get("paperId"))
    if not raw_path:
        return jsonify({"error": "paper_path is required."}), 400

    try:
        pdf_path = normalize_pdf_path(str(raw_path))
        result   = analyze_paper(pdf_path)
        paper    = result.pop("paper") if "paper" in result else paper_record(pdf_path)
        return jsonify({"paper": paper, "analysis": result})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


# =========================================================
# API — CHAT
# =========================================================

@app.post("/api/chat")
def api_chat() -> Any:
    if "user_id" not in session:
        return jsonify({"error": "Not logged in."}), 401

    from qa_engine import answer_question
    from retriever import retrieve_relevant_chunks

    data     = request.get_json(silent=True) or {}
    question = (data.get("message") or data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "message is required."}), 400

    try:
        collection_name = resolve_collection_name(data)
        info = get_index_status(collection_name)
        if info["status"] == "indexing":
            return jsonify({"error": "Paper is still being indexed. Please wait."}), 409
        if info["status"] == "error":
            return jsonify({"error": "Indexing failed. Try re-uploading."}), 500

        chunks = retrieve_relevant_chunks(question, collection_name=collection_name)
        reply  = answer_question(question, chunks)

        # Persist this exchange so it survives page refresh / server restart.
        append_chat_messages(collection_name, question, reply)

        return jsonify({"reply": reply, "collectionName": collection_name, "chunksUsed": len(chunks)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


# =========================================================
# API — CHAT HISTORY  (load saved history for a paper)
# =========================================================

@app.get("/api/chat-history/<path:paper_path>")
def api_chat_history(paper_path: str) -> Any:
    if "user_id" not in session:
        return jsonify({"error": "Not logged in."}), 401
    try:
        pdf_path        = normalize_pdf_path(paper_path)
        collection_name = collection_name_from_path(pdf_path)
        history         = get_cached_chat(collection_name)
        return jsonify({"history": history, "collectionName": collection_name})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/chat-history/clear")
def api_chat_history_clear() -> Any:
    if "user_id" not in session:
        return jsonify({"error": "Not logged in."}), 401
    data = request.get_json(silent=True) or {}
    raw_path = (data.get("paper_path") or data.get("path") or data.get("paperId"))
    if not raw_path:
        return jsonify({"error": "paper_path is required."}), 400
    try:
        pdf_path        = normalize_pdf_path(str(raw_path))
        collection_name = collection_name_from_path(pdf_path)
        clear_cached_chat(collection_name)
        return jsonify({"cleared": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


# =========================================================
# API — PREREQUISITES  (cached after first run)
# =========================================================

@app.post("/api/prerequisites")
def api_prerequisites() -> Any:
    if "user_id" not in session:
        return jsonify({"error": "Not logged in."}), 401

    try:
        from prerequisite_extractor import PrerequisiteExtractor, extract_pdf_text

        data     = request.get_json(silent=True) or {}
        raw_path = (data.get("paper_path") or data.get("path") or data.get("paperId"))
        if not raw_path:
            return jsonify({"error": "paper_path is required."}), 400

        pdf_path        = normalize_pdf_path(str(raw_path))
        collection_name = collection_name_from_path(pdf_path)

        cached = get_cached_prereqs(collection_name)
        if cached is not None:
            print(f"[prereqs] Returning cached prerequisites for {collection_name}")
            return jsonify({"prerequisites": cached, "paper_path": str(raw_path), "cached": True})

        text = extract_pdf_text(str(pdf_path))
        if len(text.strip()) < 100:
            return jsonify({"error": "Could not extract enough text."}), 400

        extractor = PrerequisiteExtractor()
        result    = extractor.extract(text)

        set_cached_prereqs(collection_name, result)
        return jsonify({"prerequisites": result, "paper_path": str(raw_path), "cached": False})

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 400


# =========================================================
# API — EXPLAIN TERM
# =========================================================

@app.post("/api/explain")
def api_explain() -> Any:
    if "user_id" not in session:
        return jsonify({"error": "Not logged in."}), 401

    try:
        from term_explainer import explain_term
        from retriever      import retrieve_relevant_chunks

        data = request.get_json(silent=True) or {}
        term = (data.get("term") or "").strip()
        if not term:
            return jsonify({"error": "term is required."}), 400

        raw_path = (data.get("paper_path") or data.get("path") or data.get("paperId"))
        if not raw_path:
            return jsonify({"error": "paper_path is required."}), 400

        pdf_path = normalize_pdf_path(str(raw_path))
        api_key  = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return jsonify({"error": "GEMINI_API_KEY missing in .env"}), 500

        collection_name = collection_name_from_path(pdf_path)
        chunks  = retrieve_relevant_chunks(term, collection_name=collection_name, top_k=5)
        result  = explain_term(term=term, chunks=chunks, api_key=api_key, paper_title=pdf_path.stem)
        return jsonify(result)

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 400


# =========================================================
# TEST ROUTE
# =========================================================

@app.get("/hello")
def hello() -> Any:
    return "HELLO WORKING"


# =========================================================
# MAIN  —  debug=True but use_reloader=FALSE
# use_reloader=True kills background threads + reloads the
# process on any file save, which nukes the in-memory caches
# and forces model re-load.  Turn it off.
# =========================================================

if __name__ == "__main__":
    print("\nFlask server starting...")
    print("http://127.0.0.1:5000\n")
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True,
        use_reloader=False,   # <-- CRITICAL: keeps background threads alive
    )