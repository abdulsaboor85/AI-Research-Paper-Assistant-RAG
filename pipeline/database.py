"""SQLite database: users, per-user known terms, per-user Gemini API key.
Creates users.db in the project root automatically."""

import hashlib
import hmac
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


@contextmanager
def db():
    """Open the database, save changes when done, always close it."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:  # commits on success, rolls back on error
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)


# =========================================================
# USERS
# =========================================================

def _legacy_hash(password: str) -> str:
    """Old SHA-256 hash. Kept ONLY so old accounts can still log in once."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def create_user(username: str, email: str, password: str) -> dict:
    username, email = username.strip(), email.strip().lower()

    if len(username) < 3:
        return {"ok": False, "error": "Username must be at least 3 characters."}
    if len(password) < 6:
        return {"ok": False, "error": "Password must be at least 6 characters."}
    if "@" not in email:
        return {"ok": False, "error": "Please enter a valid email address."}

    try:
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                (username, email, generate_password_hash(password)),
            )
        return {"ok": True, "user": {"id": cur.lastrowid, "username": username}}

    except sqlite3.IntegrityError as e:
        msg = str(e).lower()
        if "username" in msg:
            return {"ok": False, "error": "Username already taken. Please choose another."}
        if "email" in msg:
            return {"ok": False, "error": "An account with this email already exists."}
        return {"ok": False, "error": "Account creation failed. Please try again."}


def verify_user(username_or_email: str, password: str) -> dict:
    ident = username_or_email.strip()

    with db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE OR email = ? COLLATE NOCASE",
            (ident, ident),
        ).fetchone()

        if not row:
            return {"ok": False, "error": "No account found with that username or email."}

        stored = row["password"]
        if hmac.compare_digest(stored, _legacy_hash(password)):
            # Old account: upgrade to the safer hash right now.
            conn.execute(
                "UPDATE users SET password = ? WHERE id = ?",
                (generate_password_hash(password), row["id"]),
            )
        elif not check_password_hash(stored, password):
            return {"ok": False, "error": "Incorrect password. Please try again."}

    return {"ok": True, "user": {"id": row["id"], "username": row["username"]}}


# =========================================================
# KNOWN TERMS  (per-user Term Explainer memory)
# =========================================================

def add_known_term(user_id: int, term: str) -> None:
    term = term.strip().lower()
    if not term:
        return
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO known_terms (user_id, term) VALUES (?, ?)",
            (user_id, term),
        )


def get_known_terms(user_id: int) -> list[str]:
    """All terms this user learned, newest first."""
    with db() as conn:
        rows = conn.execute(
            "SELECT term FROM known_terms WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [r["term"] for r in rows]


def get_known_terms_set(user_id: int) -> set[str]:
    return set(get_known_terms(user_id))


def delete_known_term(user_id: int, term: str) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM known_terms WHERE user_id = ? AND term = ?",
            (user_id, term.strip().lower()),
        )
        return cur.rowcount > 0


def delete_all_known_terms(user_id: int) -> int:
    with db() as conn:
        return conn.execute("DELETE FROM known_terms WHERE user_id = ?", (user_id,)).rowcount


# =========================================================
# USER SETTINGS  (per-user Gemini API key)
# =========================================================

def set_gemini_api_key(user_id: int, api_key: str) -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO user_settings (user_id, gemini_api_key) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET gemini_api_key = excluded.gemini_api_key
            """,
            (user_id, api_key.strip()),
        )


def get_gemini_api_key(user_id: int) -> str | None:
    with db() as conn:
        row = conn.execute(
            "SELECT gemini_api_key FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
    return (row["gemini_api_key"] if row else None) or None


def delete_gemini_api_key(user_id: int) -> bool:
    with db() as conn:
        cur = conn.execute(
            "UPDATE user_settings SET gemini_api_key = NULL WHERE user_id = ?", (user_id,)
        )
        return cur.rowcount > 0


init_db()  # runs once when this file is imported