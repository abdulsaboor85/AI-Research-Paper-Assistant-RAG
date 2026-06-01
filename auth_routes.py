"""
PATH  ->  auth_routes.py  (project root, next to app.py)

Flask Blueprint for login / signup / logout routes.
Register this in app.py with:  app.register_blueprint(auth_bp)
"""

import sys
from pathlib import Path

from flask import Blueprint, jsonify, redirect, request, send_from_directory, session, url_for

BASE_DIR     = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
PIPELINE_DIR = BASE_DIR / "pipeline"

sys.path.insert(0, str(PIPELINE_DIR))

from database import create_user, verify_user

auth_bp = Blueprint("auth", __name__)


# ── Serve auth page ──────────────────────────────────────

@auth_bp.get("/auth")
def auth_page():
    if "user_id" in session:
        return redirect("/")
    return send_from_directory(FRONTEND_DIR, "auth.html")


@auth_bp.get("/auth.css")
def auth_css():
    return send_from_directory(FRONTEND_DIR, "auth.css")


@auth_bp.get("/auth.js")
def auth_js():
    return send_from_directory(FRONTEND_DIR, "auth.js")


# ── API: Signup ──────────────────────────────────────────

@auth_bp.post("/api/signup")
def api_signup():
    data     = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email    = (data.get("email")    or "").strip()
    password = (data.get("password") or "")

    if not username or not email or not password:
        return jsonify({"error": "All fields are required."}), 400

    result = create_user(username, email, password)

    if not result["ok"]:
        return jsonify({"error": result["error"]}), 400

    user = result["user"]
    session["user_id"]       = user["id"]
    session["username"]      = user["username"]
    session.permanent        = True

    return jsonify({
        "message":  "Account created successfully!",
        "username": user["username"],
    })


# ── API: Login ───────────────────────────────────────────

@auth_bp.post("/api/login")
def api_login():
    data             = request.get_json(silent=True) or {}
    username_or_email = (data.get("username") or data.get("email") or "").strip()
    password         = (data.get("password") or "")

    if not username_or_email or not password:
        return jsonify({"error": "Username/email and password are required."}), 400

    result = verify_user(username_or_email, password)

    if not result["ok"]:
        return jsonify({"error": result["error"]}), 401

    user = result["user"]
    session["user_id"]  = user["id"]
    session["username"] = user["username"]
    session.permanent   = True

    return jsonify({
        "message":  "Login successful!",
        "username": user["username"],
    })


# ── API: Logout ──────────────────────────────────────────

@auth_bp.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify({"message": "Logged out successfully."})


# ── API: Session check ───────────────────────────────────

@auth_bp.get("/api/me")
def api_me():
    if "user_id" not in session:
        return jsonify({"logged_in": False}), 401
    return jsonify({
        "logged_in": True,
        "user_id":   session["user_id"],
        "username":  session["username"],
    })
