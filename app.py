"""PaperInsight AI - Flask backend. Routes only; the logic lives in pipeline/."""

import json
import os
import re
import secrets
import sys
import threading
import traceback
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, request, send_from_directory, session
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

# =========================================================
# PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
UPLOAD_DIR = BASE_DIR / "papers" / "uploads"
CACHE_DIR = BASE_DIR / "cache"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")
sys.path.insert(0, str(BASE_DIR / "pipeline"))

# Load the heavy embedding model once, at startup.
print("[startup] Loading embedding model...")
import embedder  # noqa: E402
print("[startup] Ready.")

from auth_routes import auth_bp  # noqa: E402
from chunker import chunk_text  # noqa: E402
from database import (  # noqa: E402
    add_known_term, delete_all_known_terms, delete_gemini_api_key, delete_known_term,
    get_gemini_api_key, get_known_terms, get_known_terms_set, set_gemini_api_key,
)
from extractor import extract_text  # noqa: E402
from personalization import (  # noqa: E402
    parse_prereq_topics, personalize_analysis, personalize_prerequisites,
)
from prerequisite_extractor import extract_prerequisites  # noqa: E402
from qa_engine import answer_question  # noqa: E402
from retriever import retrieve_relevant_chunks  # noqa: E402
from term_explainer import explain_term  # noqa: E402

# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.register_blueprint(auth_bp)


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Not logged in."}), 401
        return view(*args, **kwargs)
    return wrapper


@app.errorhandler(Exception)
def handle_error(exc):
    """Any error inside a route becomes a JSON error for the frontend."""
    if isinstance(exc, HTTPException):
        return exc
    traceback.print_exc()
    return jsonify({"error": str(exc)}), 400


def require_api_key() -> str:
    """The user's own saved key first, then GEMINI_API_KEY from .env."""
    key = get_gemini_api_key(session["user_id"]) or os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("No Gemini API key configured. Click the gear icon to add one.")
    return key


# =========================================================
# INDEX STATUS  (per paper collection)
# =========================================================

_index_status: dict[str, dict] = {}
_index_lock = threading.Lock()


def set_index_status(name: str, status: str, step: str = "", pct: int = 0, message: str = "") -> None:
    with _index_lock:
        _index_status[name] = {"status": status, "step": step, "pct": pct, "message": message}


def get_index_status(name: str) -> dict:
    with _index_lock:
        return _index_status.get(name, {"status": "ready", "step": "", "pct": 100, "message": ""})


# =========================================================
# CACHE  (RAM + disk). Always stores the BASE result;
# personalization is applied fresh on every request.
# =========================================================

_JSON_TYPES = {"analysis", "chat"}          # "prereqs" is plain text
_ram: dict[str, dict[str, Any]] = {"analysis": {}, "prereqs": {}, "chat": {}}
_cache_lock = threading.Lock()


def _cache_path(cache_type: str, name: str) -> Path:
    safe = re.sub(r"[^a-z0-9_]", "", name.lower())
    return CACHE_DIR / f"{safe}_{cache_type}.json"


def cache_get(cache_type: str, name: str, default: Any = None) -> Any:
    with _cache_lock:
        if name in _ram[cache_type]:
            return _ram[cache_type][name]
        path = _cache_path(cache_type, name)
        if path.exists():
            try:
                raw = path.read_text(encoding="utf-8")
                value = json.loads(raw) if cache_type in _JSON_TYPES else raw
                _ram[cache_type][name] = value
                return value
            except Exception as e:
                print(f"[cache] Could not read {cache_type} cache: {e}")
    return default


def cache_set(cache_type: str, name: str, value: Any) -> None:
    with _cache_lock:
        _ram[cache_type][name] = value
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2) if cache_type in _JSON_TYPES else value
            _cache_path(cache_type, name).write_text(text, encoding="utf-8")
        except Exception as e:
            print(f"[cache] Could not write {cache_type} cache: {e}")


def cache_delete(cache_type: str, name: str) -> None:
    with _cache_lock:
        _ram[cache_type].pop(name, None)
        _cache_path(cache_type, name).unlink(missing_ok=True)


def append_chat(name: str, question: str, reply: str) -> None:
    history = list(cache_get("chat", name, []))
    history += [{"role": "user", "text": question}, {"role": "assistant", "text": reply}]
    cache_set("chat", name, history)


# =========================================================
# PAPER HELPERS
# =========================================================

TIMESTAMP_PREFIX = re.compile(r"^\d{8}_\d{6}_")


def get_user_upload_dir() -> Path:
    user_dir = UPLOAD_DIR / str(session.get("user_id", "anonymous"))
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def relative_path(path: Path) -> str:
    return path.relative_to(BASE_DIR).as_posix()


def normalize_pdf_path(raw_path: str) -> Path:
    """Turn a path from the frontend into a safe PDF path inside THIS user's uploads."""
    candidate = (BASE_DIR / raw_path.strip()).resolve()
    try:
        candidate.relative_to(get_user_upload_dir().resolve())
    except ValueError as exc:
        raise ValueError("Path must stay inside your uploads folder.") from exc
    if candidate.suffix.lower() != ".pdf":
        raise ValueError("File must be a PDF.")
    if not candidate.exists():
        raise FileNotFoundError(f"PDF not found: {raw_path}")
    return candidate


def pdf_from_request() -> Path:
    data = request.get_json(silent=True) or {}
    raw_path = data.get("paper_path")
    if not raw_path:
        raise ValueError("paper_path is required.")
    return normalize_pdf_path(str(raw_path))


def paper_title(pdf_path: Path) -> str:
    return TIMESTAMP_PREFIX.sub("", pdf_path.stem)


def collection_name_from_path(pdf_path: Path) -> str:
    folder = pdf_path.parent.relative_to(BASE_DIR).as_posix().lower()
    combined = f"{folder}/{paper_title(pdf_path).lower()}"
    return f"paper_{re.sub(r'[^a-z0-9]+', '_', combined).strip('_') or 'default'}"


def paper_record(pdf_path: Path) -> dict[str, Any]:
    name = collection_name_from_path(pdf_path)
    status = get_index_status(name)
    title = paper_title(pdf_path)
    return {
        "id": relative_path(pdf_path),
        "title": title,
        "filename": title,
        "path": relative_path(pdf_path),
        "collectionName": name,
        "modifiedAt": datetime.fromtimestamp(pdf_path.stat().st_mtime).isoformat(),
        "indexStatus": status["status"],
        "indexPct": status["pct"],
        "indexStep": status["step"],
        "indexMessage": status["message"],
    }


# =========================================================
# INDEXING  (runs in a background thread)
# =========================================================

def index_paper_background(pdf_path: Path, name: str) -> None:
    set_index_status(name, "indexing", "Starting...", 5, "Preparing to index")

    def run() -> None:
        try:
            if embedder.collection_exists_and_has_data(name):
                set_index_status(name, "ready", "Done", 100, "Ready (cached)")
                return

            set_index_status(name, "indexing", "Extracting text", 15, "Reading PDF text...")
            text = extract_text(str(pdf_path))
            if len(text.strip()) < 100:
                raise ValueError("Could not extract enough text from PDF.")

            set_index_status(name, "indexing", "Chunking", 35, "Splitting into chunks...")
            chunks = chunk_text(text)
            if not chunks:
                raise ValueError("Chunking produced no chunks.")

            set_index_status(name, "indexing", "Embedding", 55, f"Embedding {len(chunks)} chunks...")
            embedder.embed_and_store(chunks, name)

            set_index_status(name, "ready", "Done", 100, "Ready")
        except Exception as exc:
            set_index_status(name, "error", "Failed", 0, str(exc))
            print(f"[indexer] {name} failed: {exc}")

    threading.Thread(target=run, daemon=True).start()


def analyze_paper(pdf_path: Path, api_key: str) -> dict[str, Any]:
    """BASE (unpersonalized) analysis. Gemini runs only once per paper."""
    name = collection_name_from_path(pdf_path)

    cached = cache_get("analysis", name)
    if cached:
        return cached

    from difficulty_scorer import analyze_difficulty  # heavy import: load only when needed

    text = extract_text(str(pdf_path))
    if len(text.strip()) < 100:
        raise ValueError("Could not extract enough text.")

    result = analyze_difficulty(full_text=text, api_key=api_key)
    result["paper"] = paper_record(pdf_path)
    cache_set("analysis", name, result)
    return result


# =========================================================
# PAGES + FILES
# =========================================================

@app.get("/")
def index():
    if "user_id" not in session:
        return redirect("/auth")
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/style.css")
@app.get("/script.js")
def frontend_asset():
    return send_from_directory(FRONTEND_DIR, request.path.lstrip("/"))


@app.get("/uploads/<path:filename>")
@login_required
def uploads(filename: str):
    if not filename.startswith(f"{session['user_id']}/"):  # only your own files
        return jsonify({"error": "Forbidden."}), 403
    return send_from_directory(UPLOAD_DIR, filename)


# =========================================================
# API - PAPERS
# =========================================================

@app.get("/api/papers")
@login_required
def api_papers():
    pdfs = sorted(get_user_upload_dir().rglob("*.pdf"), key=lambda p: p.name.lower())
    return jsonify({"papers": [paper_record(p) for p in pdfs]})


@app.get("/api/status/<path:paper_path>")
@login_required
def api_status(paper_path: str):
    name = collection_name_from_path(normalize_pdf_path(paper_path))
    return jsonify({**get_index_status(name), "collectionName": name})


@app.post("/api/upload")
@login_required
def api_upload():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify({"error": "No file uploaded."}), 400
    if not uploaded.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files allowed."}), 400

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved_path = get_user_upload_dir() / f"{stamp}_{secure_filename(uploaded.filename)}"
    uploaded.save(saved_path)

    index_paper_background(saved_path, collection_name_from_path(saved_path))
    return jsonify({"paper": paper_record(saved_path), "analysis": {}})


# =========================================================
# API - ANALYZE / PREREQUISITES  (cached, personalized per user)
# =========================================================

@app.post("/api/analyze")
@login_required
def api_analyze():
    pdf_path = pdf_from_request()
    base_result = analyze_paper(pdf_path, require_api_key())

    known_terms = get_known_terms_set(session["user_id"])
    base_prereqs = cache_get("prereqs", collection_name_from_path(pdf_path))
    result = personalize_analysis(base_result, known_terms, base_prereqs)

    paper = result.pop("paper", None) or paper_record(pdf_path)
    return jsonify({"paper": paper, "analysis": result})


@app.post("/api/prerequisites")
@login_required
def api_prerequisites():
    pdf_path = pdf_from_request()
    name = collection_name_from_path(pdf_path)

    prereqs = cache_get("prereqs", name)
    if prereqs is None:
        api_key = require_api_key()
        text = extract_text(str(pdf_path))
        if len(text.strip()) < 100:
            raise ValueError("Could not extract enough text.")
        prereqs = extract_prerequisites(text, api_key)
        cache_set("prereqs", name, prereqs)

    personalized = personalize_prerequisites(prereqs, get_known_terms_set(session["user_id"]))
    removed = len(parse_prereq_topics(prereqs)) - len(parse_prereq_topics(personalized))
    return jsonify({"prerequisites": personalized, "filtered_count": removed})


# =========================================================
# API - CHAT
# =========================================================

@app.post("/api/chat")
@login_required
def api_chat():
    data = request.get_json(silent=True) or {}
    question = (data.get("message") or "").strip()
    if not question:
        return jsonify({"error": "message is required."}), 400

    api_key = require_api_key()
    name = collection_name_from_path(pdf_from_request())

    status = get_index_status(name)["status"]
    if status == "indexing":
        return jsonify({"error": "Paper is still being indexed. Please wait."}), 409
    if status == "error":
        return jsonify({"error": "Indexing failed. Try re-uploading."}), 500

    chunks = retrieve_relevant_chunks(question, collection_name=name)
    reply = answer_question(question, chunks, api_key)
    append_chat(name, question, reply)

    return jsonify({"reply": reply, "collectionName": name, "chunksUsed": len(chunks)})


@app.get("/api/chat-history/<path:paper_path>")
@login_required
def api_chat_history(paper_path: str):
    name = collection_name_from_path(normalize_pdf_path(paper_path))
    return jsonify({"history": cache_get("chat", name, []), "collectionName": name})


@app.post("/api/chat-history/clear")
@login_required
def api_chat_history_clear():
    cache_delete("chat", collection_name_from_path(pdf_from_request()))
    return jsonify({"cleared": True})


# =========================================================
# API - EXPLAIN TERM
# =========================================================

@app.post("/api/explain")
@login_required
def api_explain():
    data = request.get_json(silent=True) or {}
    term = (data.get("term") or "").strip()
    if not term:
        return jsonify({"error": "term is required."}), 400

    pdf_path = pdf_from_request()
    api_key = require_api_key()

    chunks = retrieve_relevant_chunks(term, collection_name=collection_name_from_path(pdf_path), top_k=5)
    result = explain_term(term, chunks, api_key, paper_title=paper_title(pdf_path))

    add_known_term(session["user_id"], term)  # remember: user has now learned this term
    return jsonify(result)


# =========================================================
# API - KNOWN TERMS (Memory)
# =========================================================

@app.get("/api/known-terms")
@login_required
def api_known_terms():
    return jsonify({"terms": get_known_terms(session["user_id"])})


@app.post("/api/known-terms/delete")
@login_required
def api_known_terms_delete():
    term = ((request.get_json(silent=True) or {}).get("term") or "").strip()
    if not term:
        return jsonify({"error": "term is required."}), 400
    return jsonify({"deleted": delete_known_term(session["user_id"], term), "term": term})


@app.post("/api/known-terms/delete-all")
@login_required
def api_known_terms_delete_all():
    return jsonify({"deleted_count": delete_all_known_terms(session["user_id"])})


# =========================================================
# API - SETTINGS (Gemini API key)
# =========================================================

def _mask_key(key: str) -> str:
    return f"{key[:4]}...{key[-4:]}" if len(key) > 8 else "••••"


@app.get("/api/settings")
@login_required
def api_settings():
    user_key = get_gemini_api_key(session["user_id"])
    if user_key:
        return jsonify({"hasKey": True, "source": "user", "masked": _mask_key(user_key)})
    env_key = os.getenv("GEMINI_API_KEY")
    if env_key:
        return jsonify({"hasKey": True, "source": "env", "masked": _mask_key(env_key)})
    return jsonify({"hasKey": False, "source": None, "masked": None})


@app.post("/api/settings/api-key")
@login_required
def api_settings_save_key():
    key = ((request.get_json(silent=True) or {}).get("api_key") or "").strip()
    if not key:
        return jsonify({"error": "API key is required."}), 400
    set_gemini_api_key(session["user_id"], key)
    return jsonify({"saved": True})


@app.post("/api/settings/api-key/delete")
@login_required
def api_settings_delete_key():
    return jsonify({"deleted": delete_gemini_api_key(session["user_id"])})


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":
    print("\nFlask server starting...\nhttp://127.0.0.1:5000\n")
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)