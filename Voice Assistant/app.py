"""
Voice Assistant - Backend
==========================
A small Flask API that sits between the browser (which handles
microphone capture, speech-to-text, and text-to-speech natively) and
the Gemini API (which generates conversational responses).

Responsibilities:
  - Serve the single-page frontend (templates/index.html + static assets).
  - Expose POST /api/chat: takes a user message + conversation history,
    calls Gemini, and returns the assistant's reply as JSON.
  - Keep the Gemini API key server-side only (never sent to the browser).

Run with:  python app.py
"""

import os
import logging

from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --------------------------------------------------------------------------- #
# Gemini configuration
# --------------------------------------------------------------------------- #
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_HISTORY_TURNS = 12  # cap conversation context sent to the model

SYSTEM_INSTRUCTION = (
    "You are Aria, a friendly, concise voice assistant. Your replies are "
    "converted to speech and spoken aloud, so: "
    "1) Keep answers short and conversational (1-3 sentences unless the "
    "user clearly asks for detail). "
    "2) Never use markdown, bullet points, asterisks, or code blocks - "
    "plain spoken sentences only. "
    "3) Spell out numbers and symbols the way a person would say them. "
    "4) Be warm and natural, like a helpful person speaking out loud."
)

_client = None
if GEMINI_API_KEY:
    _client = genai.Client(api_key=GEMINI_API_KEY)
else:
    logger.warning(
        "GEMINI_API_KEY is not set. Set it in a .env file or environment "
        "variable before starting the server."
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _build_contents(history: list, user_message: str) -> list:
    """
    Convert the frontend's plain-JSON conversation history into the
    list[types.Content] structure expected by the Gemini API, then
    append the newest user message.

    Args:
        history: List of {"role": "user" | "model", "text": str} dicts,
                 oldest first, as sent by the browser.
        user_message: The latest transcribed user utterance.

    Returns:
        A list of types.Content objects ready to pass to generate_content.
    """
    trimmed_history = history[-MAX_HISTORY_TURNS:] if history else []

    contents = [
        types.Content(role=turn["role"], parts=[types.Part(text=turn["text"])])
        for turn in trimmed_history
        if turn.get("text")
    ]
    contents.append(types.Content(role="user", parts=[types.Part(text=user_message)]))
    return contents


def generate_reply(history: list, user_message: str) -> str:
    """
    Call the Gemini API to generate a conversational reply.

    Args:
        history: Prior conversation turns (see _build_contents).
        user_message: The latest transcribed user utterance.

    Returns:
        The assistant's reply text.

    Raises:
        RuntimeError: If the client isn't configured or the API call fails.
    """
    if _client is None:
        raise RuntimeError(
            "Gemini client is not configured. Check that GEMINI_API_KEY is set."
        )

    try:
        response = _client.models.generate_content(
            model=GEMINI_MODEL,
            contents=_build_contents(history, user_message),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                max_output_tokens=300,
                temperature=0.8,
            ),
        )
        reply_text = (response.text or "").strip()
        if not reply_text:
            raise RuntimeError("Gemini returned an empty response.")
        return reply_text

    except APIError as exc:
        raise RuntimeError(f"Gemini API error: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Unexpected error calling Gemini: {exc}") from exc


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    """Serve the single-page voice assistant UI."""
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Accept a transcribed user message + conversation history, generate
    a reply via Gemini, and return it as JSON.

    Expected request body:
        {
          "message": "hello there",
          "history": [{"role": "user", "text": "..."}, {"role": "model", "text": "..."}]
        }

    Response body:
        {"reply": "..."}  on success
        {"error": "..."}  on failure (HTTP 400 / 500)
    """
    payload = request.get_json(silent=True) or {}
    user_message = (payload.get("message") or "").strip()
    history = payload.get("history") or []

    if not user_message:
        return jsonify({"error": "Message text is required."}), 400

    try:
        reply_text = generate_reply(history, user_message)
        return jsonify({"reply": reply_text})

    except RuntimeError as exc:
        logger.error("Chat generation failed: %s", exc)
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        logger.error("Unexpected server error: %s", exc)
        return jsonify({"error": "An unexpected server error occurred."}), 500


@app.route("/api/health")
def health():
    """Simple readiness check, including whether Gemini is configured."""
    return jsonify({
        "status": "ok",
        "gemini_configured": _client is not None,
        "model": GEMINI_MODEL,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
