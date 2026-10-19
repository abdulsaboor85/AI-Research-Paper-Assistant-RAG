"""
auth_routes.py  -  sign up, log in and log out.

HOW THIS FILE WORKS (easy words)
------------------------------------------------------------
1. SIGN UP:  the browser sends a username, email and password.
              We save the new user in the database and log them in.
2. LOG IN:   the browser sends a username (or email) and a password.
              We check them. If they are right, we remember the user.
3. "Remember" = we put the user's id in the "session". The session is a small
   signed cookie in the browser, so every next request knows who the user is.
4. LOG OUT:  we clear the session.

FUNCTION GUIDE
------------------------------------------------------------
   start_session   remember the user as logged in
   read_field      get a text value from the browser's data
   auth_page       show the login page (frontend/auth.html)
   api_signup      create a new account
   api_login       log in
   api_logout      log out
"""

from pathlib import Path

from flask import Blueprint, jsonify, redirect, request, send_from_directory, session

from database import create_user, verify_user

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
auth_bp = Blueprint("auth", __name__)     # a "blueprint" is a group of routes


def start_session(user):
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session.permanent = True


def read_field(data, *names):
    """Return the first non-empty text found under any of the given names."""
    for name in names:
        value = data.get(name)
        if value:
            return str(value).strip()
    return ""


@auth_bp.get("/auth")
def auth_page():
    if "user_id" in session:
        return redirect("/")
    return send_from_directory(FRONTEND_DIR, "auth.html")


@auth_bp.post("/api/signup")
def api_signup():
    data = request.get_json(silent=True) or {}
    username = read_field(data, "username")
    email = read_field(data, "email")
    password = data.get("password") or ""

    if not (username and email and password):
        return jsonify({"error": "All fields are required."}), 400

    result = create_user(username, email, password)
    if not result["ok"]:
        return jsonify({"error": result["error"]}), 400

    start_session(result["user"])
    return jsonify({"message": "Account created successfully!"})


@auth_bp.post("/api/login")
def api_login():
    data = request.get_json(silent=True) or {}
    identifier = read_field(data, "username", "email")
    password = data.get("password") or ""

    if not (identifier and password):
        return jsonify({"error": "Username/email and password are required."}), 400

    result = verify_user(identifier, password)
    if not result["ok"]:
        return jsonify({"error": result["error"]}), 401

    start_session(result["user"])
    return jsonify({"message": "Login successful!"})


@auth_bp.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify({"message": "Logged out successfully."})