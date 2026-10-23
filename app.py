"""
app.py  -  the MAIN file. Start the website with:  python app.py

HOW THIS FILE WORKS (easy words)
------------------------------------------------------------
Think of the app like a restaurant:
  * The browser page (frontend/index.html) is the CUSTOMER. It asks for things.
  * app.py is the WAITER. It takes each request and brings back an answer.
  * The files in the pipeline/ folder are the COOKS. They do the hard work
    (read the PDF, talk to Gemini, search inside the paper, compare papers).

Every "route" below is ONE thing the browser can ask for.
Example: the route "/api/upload" means "please save this PDF".

The cache: asking Gemini is slow, so after the first answer we SAVE it as a
small file in the cache/ folder. Next time we just read the file.

The comparison: the browser sends 2 or 3 paper paths. For each paper we collect
what is already saved (summary, difficulty score, roadmap). comparer.py (the cook)
puts it side by side. The AI verdict is a SECOND request, saved after the first time.

FUNCTION GUIDE
------------------------------------------------------------
 SETUP AND HELPERS
   get_secret_key          the secret key that keeps users logged in
   login_required          a guard: only logged-in users may use a route
   handle_error            turn any error into a clean {"error": "..."} answer
   read_body               read the data the browser sent
   get_api_key             the user's Gemini key (or the key from .env)
   optional_api_key        same, but None instead of an error
 PAPERS AND FILES
   get_user_upload_dir     the folder with this user's PDFs
   normalize_pdf_path      check a PDF path is safe and belongs to this user
   pdf_from_request        get the PDF path out of the browser's data
   clean_title             paper name without the date prefix
   collection_name_from_path   the name used to save a paper in the database
   lower_name              helper for sorting files by name
   title_sort_key          helper for sorting papers by title
   paper_record            all info about one paper
   list_papers             info about all papers of this user
 INDEXING (reading a paper so we can search inside it)
   set_index_status / get_index_status   remember how far indexing is
   index_paper_now         the real steps: read text, cut into chunks, save
   index_paper_background  start indexing without making the user wait
 CACHE (saved answers)
   cache_file / cache_get / cache_set / cache_delete
   analyze_paper           difficulty score (saved after the first time)
 ROUTES (what the browser can ask for)
   index                   the main page
   uploads                 send a PDF to its owner
   api_papers              list papers
   api_status              how far indexing is
   api_upload              upload a PDF
   api_analyze             difficulty score for this user
   api_summary             paper summary
   read_compare_paths      check the papers chosen for comparison
   pdf_stats               page count and reading time of a PDF
   compare_bundle          everything we know about one paper
   api_compare             compare 2 or 3 papers
   api_compare_verdict     the AI verdict for a comparison
   api_chat                answer a question about the paper
   api_chat_history        the saved chat
   api_prerequisites       learning roadmap for this user
   api_explain             explain a term (and save it to Memory)
   api_known_terms         list the terms the user learned (Memory)
   api_known_terms_delete / api_known_terms_delete_all   forget terms
   mask_key                hide most of an API key
   api_settings / api_settings_save_key / api_settings_delete_key   Gemini key
"""

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

import fitz        # PyMuPDF: we use it to count the pages of a PDF
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, request, send_from_directory, session
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------
# Folders
# ---------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
UPLOAD_DIR = BASE_DIR / "papers" / "uploads"
CACHE_DIR = BASE_DIR / "cache"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")
sys.path.insert(0, str(BASE_DIR / "pipeline"))   # so we can import from pipeline/

# The "cooks" from the pipeline/ folder
print("[startup] Loading embedding model...")
from embedder import collection_exists_and_has_data, embed_and_store
from auth_routes import auth_bp
from chunker import chunk_text
from comparer import (MAX_PAPERS, MIN_PAPERS, build_comparison, build_verdict,
                      comparison_key, relatedness)
from database import (add_known_term, delete_all_known_terms, delete_gemini_api_key,
                       delete_known_term, get_gemini_api_key, get_known_terms,
                       get_known_terms_set, set_gemini_api_key)
from extractor import MIN_TEXT_LENGTH, extract_text
from personalization import parse_prereq_topics, personalize_analysis, personalize_prerequisites
from prerequisite_extractor import extract_prerequisites
from qa_engine import answer_question
from retriever import retrieve_relevant_chunks
from summarizer import cut_references, summarize_paper
from term_explainer import explain_term


# ---------------------------------------------------------------
# Setup and helpers :: creating a secrete key
# ---------------------------------------------------------------
def get_secret_key():
    """The secret key signs the login cookie. We save it in a file, so users
    stay logged in even after the server restarts."""
    key = os.getenv("SECRET_KEY")
    if key:
        return key

    key_file = BASE_DIR / ".secret_key"
    try:
        if key_file.exists():
            saved = key_file.read_text(encoding="utf-8").strip()
            if saved:
                return saved
    except OSError:
        pass

    key = secrets.token_hex(32)
    try:
        key_file.write_text(key, encoding="utf-8")
    except OSError:
        print("[startup] Could not save .secret_key. Users will be logged out on restart.")
    return key


app = Flask(__name__)
app.secret_key = get_secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024    # biggest upload: 50 MB
app.register_blueprint(auth_bp)                         # login / signup routes

# check is user logged in or not 
def login_required(route_function):
    """Write @login_required above a route. Then only logged-in users can use it."""
    @wraps(route_function)
    def guarded(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Not logged in."}), 401
        return route_function(*args, **kwargs)
    return guarded


@app.errorhandler(Exception)
def handle_error(error):
    """If anything goes wrong inside /api/, answer {"error": "message"}."""
    if isinstance(error, HTTPException):
        if not request.path.startswith("/api/"):
            return error
        if error.code == 413:
            message = "File too large (max 50 MB)."
        else:
            message = error.description or error.name
        return jsonify({"error": message}), (error.code or 500)

    traceback.print_exc()
    if isinstance(error, (ValueError, FileNotFoundError)):
        status = 400
    else:
        status = 500
    return jsonify({"error": str(error)}), status


def read_body():
    """The data (JSON) the browser sent. An empty dict if there is none."""
    return request.get_json(silent=True) or {}

#check api key in session then in env file  
def get_api_key():
    """The user's own Gemini key. If they have none, use the key from .env."""
    key = get_gemini_api_key(session["user_id"]) or os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("No Gemini API key configured. Click the gear icon to add one.")
    return key


def optional_api_key():
    """Same as get_api_key, but returns None when there is no key.
    Used when the saved results may already exist, so no key is needed."""
    try:
        return get_api_key()
    except ValueError:
        return None


# ---------------------------------------------------------------
# Papers and files
# ---------------------------------------------------------------
DATE_PREFIX = re.compile(r"^\d{8}_\d{6}_")     # uploaded files start with 20260101_120000_

#make folder with user id
def get_user_upload_dir():
    """The folder that holds this user's PDFs (made if it does not exist)."""
    user_dir = UPLOAD_DIR / str(session.get("user_id", "anonymous"))
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def normalize_pdf_path(raw_path):
    """Only allow PDFs inside the CURRENT user's own folder."""
    #This is the trick that catches hackers e.g papers/uploads/1/../2/secret.pdf.
    user_dir = get_user_upload_dir().resolve()
    candidate = (BASE_DIR / raw_path.strip()).resolve()

    try:
        candidate.relative_to(user_dir)
    except ValueError:
        raise ValueError("You can only open your own papers.")

    if candidate.suffix.lower() != ".pdf":
        raise ValueError("File must be a PDF.")
    if not candidate.exists():
        raise FileNotFoundError("PDF not found: " + raw_path)
    return candidate


def pdf_from_request(data):
    raw_path = data.get("paper_path")
    if not raw_path:
        raise ValueError("paper_path is required.")
    return normalize_pdf_path(str(raw_path))

#20260101_120000_paper.pdf -> paper
def clean_title(pdf_path):
    return DATE_PREFIX.sub("", pdf_path.stem)


def collection_name_from_path(pdf_path):
    """The name used to save this paper in the search database and in the cache."""
    folder = pdf_path.parent.relative_to(BASE_DIR).as_posix().lower()
    stem = DATE_PREFIX.sub("", pdf_path.stem.lower())
    safe = re.sub(r"[^a-z0-9]+", "_", folder + "/" + stem).strip("_")
    if not safe:
        safe = "default"
    return "paper_" + safe


def lower_name(path):
    return path.name.lower()


def title_sort_key(path):
    """Sort papers by title, so Paper A, B, C is the same in every comparison."""
    return clean_title(path).lower()


def paper_record(pdf_path):
    """All the info about one paper. This is what the browser receives."""
    name = collection_name_from_path(pdf_path)
    index = get_index_status(name)
    return {
        "id": pdf_path.relative_to(BASE_DIR).as_posix(),
        "title": clean_title(pdf_path),
        "path": pdf_path.relative_to(BASE_DIR).as_posix(),
        "collectionName": name,
        "indexStatus": index["status"],
        "indexPct": index["pct"],
        "indexStep": index["step"],
        "indexMessage": index["message"],
    }


def list_papers():
    pdfs = []
    for path in get_user_upload_dir().rglob("*.pdf"):
        if path.is_file():
            pdfs.append(path)
    pdfs.sort(key=lower_name)

    records = []
    for pdf in pdfs:
        records.append(paper_record(pdf))
    return records


# ---------------------------------------------------------------
# Indexing: read a paper and save it, so we can search inside it
# ---------------------------------------------------------------
index_status = {}      # paper name -> how far indexing is
READY = {"status": "ready", "step": "", "pct": 100, "message": ""}


def set_index_status(name, status, step="", pct=0, message=""):
    index_status[name] = {"status": status, "step": step, "pct": pct, "message": message}


def get_index_status(name):
    return index_status.get(name, READY)


def index_paper_now(pdf_path, name):
    """The real steps: read the text -> cut it into chunks -> save the chunks."""
    try:
        if collection_exists_and_has_data(name):
            set_index_status(name, "ready", "Done", 100, "Ready (cached)")
            return

        set_index_status(name, "indexing", "Extracting text", 15, "Reading PDF text...")
        text = extract_text(str(pdf_path))
        if len(text.strip()) < MIN_TEXT_LENGTH:
            raise ValueError("Could not extract enough text from PDF.")

        set_index_status(name, "indexing", "Chunking", 35, "Splitting into chunks...")
        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("Chunking produced no chunks.")

        set_index_status(name, "indexing", "Embedding", 55, "Embedding " + str(len(chunks)) + " chunks...")
        embed_and_store(chunks, collection_name=name, force=False)
        set_index_status(name, "ready", "Done", 100, "Ready")
    except Exception as error:
        traceback.print_exc()
        set_index_status(name, "error", "Failed", 0, str(error))


def index_paper_background(pdf_path, name):
    """Start indexing in a separate thread, so the upload answers right away."""
    set_index_status(name, "indexing", "Starting...", 5, "Preparing to index")
    thread = threading.Thread(target=index_paper_now, args=(pdf_path, name), daemon=True)
    thread.start()


# ---------------------------------------------------------------
# Cache: saved answers (one small file per answer)
# ---------------------------------------------------------------
def cache_file(kind, key):
    safe_key = re.sub(r"[^a-z0-9_]", "", key.lower())
    return CACHE_DIR / (safe_key + "_" + kind + ".json")


def cache_get(kind, key, is_json=True):
    """Read a saved answer. Returns None if nothing is saved."""
    path = cache_file(kind, key)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        if is_json:
            return json.loads(text)
        return text
    except Exception as error:
        print("[cache] could not read", kind, ":", error)
        return None


def cache_set(kind, key, value, is_json=True):
    """Save an answer."""
    try:
        if is_json:
            text = json.dumps(value, ensure_ascii=False, indent=2)
        else:
            text = value
        cache_file(kind, key).write_text(text, encoding="utf-8")
    except Exception as error:
        print("[cache] could not save", kind, ":", error)


def cache_delete(kind, key):
    try:
        cache_file(kind, key).unlink(missing_ok=True)
    except Exception as error:
        print("[cache] could not delete", kind, ":", error)


def analyze_paper(pdf_path, api_key):
    """The difficulty score (before personalizing). Gemini runs once per paper."""
    from difficulty_scorer import analyze_difficulty    # slow to load, so import only when needed

    name = collection_name_from_path(pdf_path)
    saved = cache_get("analysis", name)
    if saved:
        return saved

    text = extract_text(str(pdf_path))
    if len(text.strip()) < MIN_TEXT_LENGTH:
        raise ValueError("Could not extract enough text.")

    result = analyze_difficulty(text, api_key)
    cache_set("analysis", name, result)
    return result


# ---------------------------------------------------------------
# ROUTES: pages and PDF files
# ---------------------------------------------------------------
@app.get("/")
def index():
    """The main page. Not logged in? Go to the login page."""
    if "user_id" not in session:
        return redirect("/auth")
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/uploads/<path:filename>")
@login_required
def uploads(filename):
    """Send a PDF, but only to its owner (the first folder name is the user id)."""
    first_part = filename.replace("\\", "/").split("/")[0]
    if first_part != str(session["user_id"]):
        abort(403)
    return send_from_directory(UPLOAD_DIR, filename)


# ---------------------------------------------------------------
# ROUTES: papers
# ---------------------------------------------------------------
@app.get("/api/papers")
@login_required
def api_papers():
    return jsonify({"papers": list_papers()})


@app.get("/api/status/<path:paper_path>")
@login_required
def api_status(paper_path):
    name = collection_name_from_path(normalize_pdf_path(paper_path))
    answer = dict(get_index_status(name))
    answer["collectionName"] = name
    return jsonify(answer)


@app.post("/api/upload")
@login_required
def api_upload():
    uploaded = request.files.get("file")
    if uploaded is None:
        return jsonify({"error": "No file uploaded."}), 400
    if not uploaded.filename:
        return jsonify({"error": "Empty filename."}), 400
    if not uploaded.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files allowed."}), 400

    # A real PDF always starts with the letters %PDF-
    first_bytes = uploaded.stream.read(5)
    uploaded.stream.seek(0)
    if first_bytes != b"%PDF-":
        return jsonify({"error": "This file is not a valid PDF."}), 400

    # A safe file name that always ends with .pdf
    safe_stem = secure_filename(Path(uploaded.filename).stem)
    if not safe_stem:
        safe_stem = "paper"
    new_name = safe_stem + ".pdf"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Delete older copies of the same paper
    user_dir = get_user_upload_dir()
    for old_file in user_dir.glob("*.pdf"):
        if DATE_PREFIX.sub("", old_file.name).lower() == new_name.lower():
            try:
                old_file.unlink()
            except OSError:
                print("[upload] could not delete the old copy", old_file.name)

    saved_path = user_dir / (stamp + "_" + new_name)
    uploaded.save(saved_path)

    index_paper_background(saved_path, collection_name_from_path(saved_path))
    return jsonify({"paper": paper_record(saved_path)})


# ---------------------------------------------------------------
# ROUTES: difficulty score and summary
# ---------------------------------------------------------------
@app.post("/api/analyze")
@login_required
def api_analyze():
    pdf_path = pdf_from_request(read_body())
    base_result = analyze_paper(pdf_path, get_api_key())

    known_terms = get_known_terms_set(session["user_id"])
    prereq_text = cache_get("prereqs", collection_name_from_path(pdf_path), is_json=False)
    result = personalize_analysis(base_result, known_terms, prereq_text)
    return jsonify({"analysis": result})


@app.post("/api/summary")
@login_required
def api_summary():
    data = read_body()
    pdf_path = pdf_from_request(data)
    name = collection_name_from_path(pdf_path)

    if data.get("force"):
        cache_delete("summary3", name)

    summary = cache_get("summary3", name)
    if summary is None:
        summary = summarize_paper(str(pdf_path), get_api_key(), clean_title(pdf_path), name)
        cache_set("summary3", name, summary)
    return jsonify({"summary": summary})


# ---------------------------------------------------------------
# ROUTES: comparison
# ---------------------------------------------------------------
def read_compare_paths(data):
    """Check the chosen papers. Returns them sorted by title (so A, B, C never change)."""
    raw_list = data.get("paper_paths")
    if not isinstance(raw_list, list):
        raise ValueError("paper_paths must be a list.")

    paths = []
    for item in raw_list:
        path = normalize_pdf_path(str(item))
        if path not in paths:           # the same paper twice counts once
            paths.append(path)

    if len(paths) < MIN_PAPERS:
        raise ValueError("Pick at least " + str(MIN_PAPERS) + " different papers.")
    if len(paths) > MAX_PAPERS:
        raise ValueError("You can compare up to " + str(MAX_PAPERS) + " papers.")

    paths.sort(key=title_sort_key)
    return paths


def pdf_stats(pdf_path):
    """Returns (number of pages, minutes to read). We guess 200 words per minute."""
    with fitz.open(str(pdf_path)) as document:
        pages = document.page_count
    words = len(cut_references(extract_text(str(pdf_path))).split())
    minutes = max(1, round(words / 200))
    return pages, minutes


def compare_bundle(pdf_path, api_key):
    """Everything we know about ONE paper. Uses saved results, makes only what is missing."""
    name = collection_name_from_path(pdf_path)

    summary = cache_get("summary3", name)
    if summary is None:
        summary = summarize_paper(str(pdf_path), api_key, clean_title(pdf_path), name)
        cache_set("summary3", name, summary)

    pages, minutes = pdf_stats(pdf_path)
    return {
        "name": name,
        "title": clean_title(pdf_path),
        "path": pdf_path.relative_to(BASE_DIR).as_posix(),
        "summary": summary,
        "analysis": analyze_paper(pdf_path, api_key),
        "prereqs": cache_get("prereqs", name, is_json=False),
        "pages": pages,
        "read_minutes": minutes,
    }


@app.post("/api/compare")
@login_required
def api_compare():
    paths = read_compare_paths(read_body())
    api_key = optional_api_key()
    known_terms = get_known_terms_set(session["user_id"])

    bundles = []
    for path in paths:
        bundles.append(compare_bundle(path, api_key))
    return jsonify(build_comparison(bundles, known_terms))


@app.post("/api/compare/verdict")
@login_required
def api_compare_verdict():
    paths = read_compare_paths(read_body())

    bundles = []
    for path in paths:
        bundles.append(compare_bundle(path, optional_api_key()))
    level = relatedness(bundles)["level"]

    key = comparison_key(bundles, level)
    verdict = cache_get("verdict", key)
    was_saved = verdict is not None
    if not was_saved:
        verdict = build_verdict(bundles, level, get_api_key())
        cache_set("verdict", key, verdict)
    return jsonify({"verdict": verdict, "cached": was_saved})


# ---------------------------------------------------------------
# ROUTES: chat
# ---------------------------------------------------------------
@app.post("/api/chat")
@login_required
def api_chat():
    data = read_body()
    question = (data.get("message") or "").strip()
    if not question:
        return jsonify({"error": "message is required."}), 400

    api_key = get_api_key()
    name = collection_name_from_path(pdf_from_request(data))
    status = get_index_status(name)["status"]
    if status == "indexing":
        return jsonify({"error": "Paper is still being indexed. Please wait."}), 409
    if status == "error":
        return jsonify({"error": "Indexing failed. Try re-uploading."}), 500

    chunks = retrieve_relevant_chunks(question, collection_name=name)
    reply = answer_question(question, chunks, api_key=api_key)

    # save the question and answer in the chat history
    history = cache_get("chat", name) or []
    history.append({"role": "user", "text": question})
    history.append({"role": "assistant", "text": reply})
    cache_set("chat", name, history)

    return jsonify({"reply": reply})


@app.get("/api/chat-history/<path:paper_path>")
@login_required
def api_chat_history(paper_path):
    name = collection_name_from_path(normalize_pdf_path(paper_path))
    return jsonify({"history": cache_get("chat", name) or []})


# ---------------------------------------------------------------
# ROUTES: prerequisites
# ---------------------------------------------------------------
@app.post("/api/prerequisites")
@login_required
def api_prerequisites():
    pdf_path = pdf_from_request(read_body())
    name = collection_name_from_path(pdf_path)

    prereqs = cache_get("prereqs", name, is_json=False)
    if prereqs is None:
        api_key = get_api_key()
        text = extract_text(str(pdf_path))
        if len(text.strip()) < MIN_TEXT_LENGTH:
            raise ValueError("Could not extract enough text.")
        prereqs = extract_prerequisites(text, api_key)
        cache_set("prereqs", name, prereqs, is_json=False)

    # remove the topics this user already knows
    known_terms = get_known_terms_set(session["user_id"])
    personalized = personalize_prerequisites(prereqs, known_terms)
    removed = len(parse_prereq_topics(prereqs)) - len(parse_prereq_topics(personalized))
    return jsonify({"prerequisites": personalized, "filtered_count": removed})


# ---------------------------------------------------------------
# ROUTES: explain a term
# ---------------------------------------------------------------
@app.post("/api/explain")
@login_required
def api_explain():
    data = read_body()
    term = (data.get("term") or "").strip()
    if not term:
        return jsonify({"error": "term is required."}), 400

    pdf_path = pdf_from_request(data)
    api_key = get_api_key()
    name = collection_name_from_path(pdf_path)
    chunks = retrieve_relevant_chunks(term, collection_name=name, top_k=5)
    result = explain_term(term, chunks, api_key, clean_title(pdf_path))

    add_known_term(session["user_id"], term)     # Memory: the user has now learned this term
    return jsonify(result)


# ---------------------------------------------------------------
# ROUTES: Memory (the terms the user has learned)
# ---------------------------------------------------------------
@app.get("/api/known-terms")
@login_required
def api_known_terms():
    return jsonify({"terms": get_known_terms(session["user_id"])})


@app.post("/api/known-terms/delete")
@login_required
def api_known_terms_delete():
    term = (read_body().get("term") or "").strip()
    if not term:
        return jsonify({"error": "term is required."}), 400
    deleted = delete_known_term(session["user_id"], term)
    return jsonify({"deleted": deleted, "term": term})


@app.post("/api/known-terms/delete-all")
@login_required
def api_known_terms_delete_all():
    return jsonify({"deleted_count": delete_all_known_terms(session["user_id"])})


# ---------------------------------------------------------------
# ROUTES: settings (the user's Gemini API key)
# ---------------------------------------------------------------
def mask_key(key):
    """Show only the first and last 4 letters, like AIza...x9Zq"""
    if len(key) > 8:
        return key[:4] + "..." + key[-4:]
    return "••••"


@app.get("/api/settings")
@login_required
def api_settings():
    user_key = get_gemini_api_key(session["user_id"])
    if user_key:
        return jsonify({"hasKey": True, "source": "user", "masked": mask_key(user_key)})

    env_key = os.getenv("GEMINI_API_KEY")
    if env_key:
        return jsonify({"hasKey": True, "source": "env", "masked": mask_key(env_key)})

    return jsonify({"hasKey": False, "source": None, "masked": None})


@app.post("/api/settings/api-key")
@login_required
def api_settings_save_key():
    key = (read_body().get("api_key") or "").strip()
    if not key:
        return jsonify({"error": "API key is required."}), 400
    set_gemini_api_key(session["user_id"], key)
    return jsonify({"saved": True})


@app.post("/api/settings/api-key/delete")
@login_required
def api_settings_delete_key():
    return jsonify({"deleted": delete_gemini_api_key(session["user_id"])})


# ---------------------------------------------------------------
# Start the server
# ---------------------------------------------------------------
if __name__ == "__main__":
    print("\nFlask server starting...\nhttp://127.0.0.1:5000\n")
    app.run(host="127.0.0.1", port=5000,
            debug=(os.getenv("FLASK_DEBUG") == "1"), use_reloader=False)