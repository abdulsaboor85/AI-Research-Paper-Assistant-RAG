"""
PATH  ->  pipeline/database.py

Handles SQLite user database for PaperMind authentication.
Creates users.db in the project root automatically.
"""

import hashlib
import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH  = BASE_DIR / "users.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create users table if it doesn't exist."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                email      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                password   TEXT    NOT NULL,
                created_at TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def create_user(username: str, email: str, password: str) -> dict:
    """
    Insert a new user. Returns dict with success/error.
    """
    if len(username.strip()) < 3:
        return {"ok": False, "error": "Username must be at least 3 characters."}
    if len(password) < 6:
        return {"ok": False, "error": "Password must be at least 6 characters."}
    if "@" not in email:
        return {"ok": False, "error": "Please enter a valid email address."}

    hashed = hash_password(password)

    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                (username.strip(), email.strip().lower(), hashed),
            )
            conn.commit()

        user = get_user_by_username(username)
        return {"ok": True, "user": dict(user)}

    except sqlite3.IntegrityError as e:
        msg = str(e)
        if "username" in msg.lower():
            return {"ok": False, "error": "Username already taken. Please choose another."}
        if "email" in msg.lower():
            return {"ok": False, "error": "An account with this email already exists."}
        return {"ok": False, "error": "Account creation failed. Please try again."}


def verify_user(username_or_email: str, password: str) -> dict:
    """
    Check credentials. Returns dict with success/error.
    Accepts either username or email in the first field.
    """
    hashed = hash_password(password)

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM users
            WHERE (username = ? COLLATE NOCASE OR email = ? COLLATE NOCASE)
              AND password = ?
            """,
            (username_or_email.strip(), username_or_email.strip().lower(), hashed),
        ).fetchone()

    if row:
        return {"ok": True, "user": dict(row)}

    # Check if user exists to give a helpful error
    with get_connection() as conn:
        exists = conn.execute(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE OR email = ? COLLATE NOCASE",
            (username_or_email.strip(), username_or_email.strip().lower()),
        ).fetchone()

    if exists:
        return {"ok": False, "error": "Incorrect password. Please try again."}

    return {"ok": False, "error": "No account found with that username or email."}


def get_user_by_username(username: str):
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, username, email, created_at FROM users WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        ).fetchone()


# Auto-initialise on import
init_db()
