"""
database.py  -  the small database file  users.db  (SQLite).

HOW THIS FILE WORKS (easy words)
------------------------------------------------------------
SQLite saves data in ONE file. We use three tables (think: three Excel sheets):
  * users          - username, email, password
  * known_terms    - the words each user has learned (this is "Memory")
  * user_settings  - each user's own Gemini API key
To read or write data we send short commands written in SQL.
The "?" in a command is a safe placeholder for a value.
Passwords are never saved as plain text. They are scrambled ("hashed").

FUNCTION GUIDE
------------------------------------------------------------
   get_connection         open the database (saves on success, undoes on error)
   init_db                make the tables if they do not exist yet
   hash_password          OLD way to scramble passwords (only for old accounts)
   is_old_hash            was this password saved the old way?
   password_is_correct    check a typed password against the saved one
   get_user_by_username   find a user by name
   create_user            make a new account
   verify_user            check username/email + password at login
   add_known_term         save a term the user learned
   get_known_terms        list the user's learned terms (newest first)
   get_known_terms_set    same list, as a set (fast to search)
   delete_known_term      forget one term
   delete_all_known_terms forget all terms
   set_gemini_api_key / get_gemini_api_key / delete_gemini_api_key
"""

import hashlib
import hmac
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = Path(__file__).resolve().parent.parent / "users.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password   TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS known_terms (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    term       TEXT NOT NULL COLLATE NOCASE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, term),
    FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS user_settings (
    user_id        INTEGER PRIMARY KEY,
    gemini_api_key TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
"""

OLD_HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")   # an old password looks like 64 letters/numbers


@contextmanager
def get_connection():
    """Use it like:   with get_connection() as conn:
    It saves your changes when the block ends well, undoes them on an error,
    and always closes the database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row         # lets us read a column by name: row["term"]
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------
def hash_password(password):
    """OLD way (unsalted SHA-256). Used ONLY to check and upgrade old accounts."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def is_old_hash(saved):
    return bool(OLD_HASH_PATTERN.match(saved or ""))


def password_is_correct(saved, password):
    if is_old_hash(saved):
        return hmac.compare_digest(saved.lower().encode("utf-8"),
                                   hash_password(password).encode("utf-8"))
    try:
        return check_password_hash(saved, password)
    except Exception:
        return False


# ---------------------------------------------------------------
# Users
# ---------------------------------------------------------------
def get_user_by_username(username):
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, username, email, created_at FROM users WHERE username = ?",
            (username.strip(),)
        ).fetchone()


def create_user(username, email, password):
    """Returns {"ok": True, "user": {...}} or {"ok": False, "error": "..."}"""
    username = username.strip()
    email = email.strip().lower()

    if len(username) < 3:
        return {"ok": False, "error": "Username must be at least 3 characters."}
    if len(password) < 6:
        return {"ok": False, "error": "Password must be at least 6 characters."}
    if "@" not in email:
        return {"ok": False, "error": "Please enter a valid email address."}

    try:
        with get_connection() as conn:
            conn.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                         (username, email, generate_password_hash(password)))
    except sqlite3.IntegrityError as error:
        message = str(error).lower()
        if "username" in message:
            return {"ok": False, "error": "Username already taken. Please choose another."}
        if "email" in message:
            return {"ok": False, "error": "An account with this email already exists."}
        return {"ok": False, "error": "Account creation failed. Please try again."}

    return {"ok": True, "user": dict(get_user_by_username(username))}


def verify_user(username_or_email, password):
    """Returns {"ok": True, "user": {...}} or {"ok": False, "error": "..."}"""
    identifier = username_or_email.strip()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ? OR email = ?",
                           (identifier, identifier)).fetchone()

    if not row:
        return {"ok": False, "error": "No account found with that username or email."}

    saved = row["password"]
    if not password_is_correct(saved, password):
        return {"ok": False, "error": "Incorrect password. Please try again."}

    # An old account: switch to the safer password storage after a good login
    if is_old_hash(saved):
        try:
            with get_connection() as conn:
                conn.execute("UPDATE users SET password = ? WHERE id = ?",
                             (generate_password_hash(password), row["id"]))
        except sqlite3.Error:
            print("[database] could not upgrade the old password")

    user = dict(row)
    del user["password"]          # never send the password around
    return {"ok": True, "user": user}


# ---------------------------------------------------------------
# Memory: the terms the user has learned
# ---------------------------------------------------------------
def add_known_term(user_id, term):
    term = term.strip().lower()
    if not term:
        return
    with get_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO known_terms (user_id, term) VALUES (?, ?)",
                     (user_id, term))


def get_known_terms(user_id):
    with get_connection() as conn:
        rows = conn.execute("SELECT term FROM known_terms WHERE user_id = ? ORDER BY created_at DESC",
                            (user_id,)).fetchall()
    terms = []
    for row in rows:
        terms.append(row["term"])
    return terms


def get_known_terms_set(user_id):
    return set(get_known_terms(user_id))


def delete_known_term(user_id, term):
    """True if a term was deleted."""
    with get_connection() as conn:
        result = conn.execute("DELETE FROM known_terms WHERE user_id = ? AND term = ?",
                              (user_id, term.strip().lower()))
        return result.rowcount > 0


def delete_all_known_terms(user_id):
    """Returns how many terms were deleted."""
    with get_connection() as conn:
        result = conn.execute("DELETE FROM known_terms WHERE user_id = ?", (user_id,))
        return result.rowcount


# ---------------------------------------------------------------
# The user's own Gemini API key
# ---------------------------------------------------------------
def set_gemini_api_key(user_id, api_key):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO user_settings (user_id, gemini_api_key) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET gemini_api_key = excluded.gemini_api_key""",
            (user_id, api_key.strip()))


def get_gemini_api_key(user_id):
    """The saved key, or None."""
    with get_connection() as conn:
        row = conn.execute("SELECT gemini_api_key FROM user_settings WHERE user_id = ?",
                           (user_id,)).fetchone()
    if row and row["gemini_api_key"]:
        return row["gemini_api_key"]
    return None


def delete_gemini_api_key(user_id):
    with get_connection() as conn:
        result = conn.execute("UPDATE user_settings SET gemini_api_key = NULL WHERE user_id = ?",
                              (user_id,))
        return result.rowcount > 0


init_db()     # make the tables as soon as this file is loaded