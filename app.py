import os
from flask import Flask, request, jsonify, session
from flask_cors import CORS
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from google import genai
from google.genai import types

from database import get_db, init_db

load_dotenv()

app = Flask(__name__)

# Needed for Flask's session cookies (login state) to work securely.
# In production, set this via an environment variable instead of hardcoding it.
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-this-in-production")

# supports_credentials is required so the browser will send/receive the session cookie
CORS(app, supports_credentials=True)

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Make sure the users table exists before the app starts handling requests.
init_db()

# NOTE: still a single shared conversation for now (not per-user yet).
# Once accounts are working end to end, this is the next thing worth fixing.
conversation_history = []


# ---------------------------------------------------------------------------
# AUTH ROUTES
# ---------------------------------------------------------------------------

@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400

    password_hash = generate_password_hash(password)

    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            (email, password_hash)
        )
        db.commit()
    except Exception:
        db.close()
        return jsonify({"error": "An account with that email already exists."}), 409

    db.close()

    # Log them in immediately after registering
    session["user_email"] = email
    return jsonify({"status": "registered", "email": email})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE email = ?", (email,)
    ).fetchone()
    db.close()

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid email or password."}), 401

    session["user_email"] = email
    return jsonify({"status": "logged_in", "email": email})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.pop("user_email", None)
    return jsonify({"status": "logged_out"})


@app.route("/api/me", methods=["GET"])
def me():
    """Lets the frontend check if someone is currently logged in."""
    email = session.get("user_email")
    if not email:
        return jsonify({"logged_in": False})
    return jsonify({"logged_in": True, "email": email})


# ---------------------------------------------------------------------------
# CHAT ROUTES
# ---------------------------------------------------------------------------

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    conversation_history.append(
        types.Content(role="user", parts=[types.Part(text=user_message)])
    )

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=conversation_history
        )

        reply_text = response.text

        conversation_history.append(
            types.Content(role="model", parts=[types.Part(text=reply_text)])
        )

        return jsonify({"reply": reply_text})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/new-chat", methods=["POST"])
def new_chat():
    conversation_history.clear()
    return jsonify({"status": "cleared"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)