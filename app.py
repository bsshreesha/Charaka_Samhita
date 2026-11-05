from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
import logging
import os
import re
import traceback

from charaka_backend.config import GITHUB_REPOSITORY, GITHUB_BRANCH
from charaka_backend.repository import build_index, load_index
from charaka_backend.search import search_passages

app = Flask(__name__)
CORS(app)
app.logger.setLevel(logging.INFO)


def current_index():
    """Load the generated corpus index; build only when it is absent."""
    index = load_index()
    if index is None:
        app.logger.warning("Index is missing; attempting a build.")
        build_index()
        index = load_index()

    if index is None:
        raise RuntimeError(
            "Search index is missing or could not be loaded. "
            "Check the Render build logs and the configured index path."
        )
    return index


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/health")
def health():
    """This route must return health information, never the search instructions."""
    try:
        index = load_index()
        return jsonify({
            "status": "ok",
            "service": "Charaka Samhita Symptom Reference API",
            "repository": GITHUB_REPOSITORY,
            "branch": GITHUB_BRANCH,
            "index_ready": index is not None,
            "chapter_count": index.get("chapter_count", 0) if index else 0,
            "passage_count": len(index.get("passages", [])) if index else 0,
            "failed_chapters": index.get("failed_chapters", []) if index else [],
        }), 200
    except Exception:
        app.logger.exception("Health endpoint failed")
        return jsonify({
            "status": "error",
            "message": "Health check could not inspect the index. Check Render logs."
        }), 500


@app.post("/api/index/rebuild")
def rebuild_index():
    try:
        manifest = build_index(force=True)
        return jsonify({"status": "built", "manifest": manifest}), 200
    except Exception:
        app.logger.exception("Index rebuild failed")
        return jsonify({
            "error": "Index rebuild failed. Check the Render service logs."
        }), 500


@app.get("/api/symptoms")
def symptoms():
    try:
        from charaka_backend.search import ALIASES
        return jsonify({"symptoms": sorted(ALIASES.keys())}), 200
    except Exception:
        app.logger.exception("Could not load symptom aliases")
        return jsonify({"error": "Could not load symptom suggestions."}), 500


@app.route("/api/search", methods=["GET", "POST"])
def search():
    if request.method == "GET":
        return jsonify({
            "service": "Charaka Samhita Symptom Reference API",
            "endpoint": "/api/search",
            "accepted_method_for_search": "POST",
            "content_type": "application/json",
            "example": {
                "symptoms": [
                    "fever",
                    "excessive thirst",
                    "burning sensation",
                    "loss of appetite"
                ]
            },
            "instruction": (
                "Open the application homepage to use the practitioner interface, "
                "or send a POST request with a JSON symptoms field."
            )
        }), 200

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "error": "Expected a JSON request body.",
            "example": {"symptoms": ["fever", "thirst"]}
        }), 400

    symptoms_value = payload.get("symptoms", [])
    if isinstance(symptoms_value, str):
        symptoms_value = [
            item.strip()
            for item in re.split(
                r"[,;\n\r]+|\s+\band\b\s+",
                symptoms_value,
                flags=re.IGNORECASE
            )
            if item.strip()
        ]

    if not isinstance(symptoms_value, list):
        return jsonify({
            "error": "The symptoms field must be a string or a list of strings."
        }), 400

    symptoms_value = [
        str(item).strip()
        for item in symptoms_value
        if str(item).strip()
    ]
    if not symptoms_value:
        return jsonify({"error": "Please enter at least one symptom."}), 400

    try:
        index = current_index()
        try:
            limit = max(1, min(int(payload.get("limit", 25)), 100))
        except (TypeError, ValueError):
            limit = 25

        passages = index.get("passages", [])
        if not isinstance(passages, list):
            raise TypeError(
                "The loaded index has an unexpected format: 'passages' is not a list."
            )

        results = search_passages(passages, symptoms_value, limit)

        return jsonify({
            "query": {"symptoms": symptoms_value},
            "result_count": len(results),
            "results": results,
            "primary_reference": results[0] if results else None,
            "other_probable_diseases": results[1:] if len(results) > 1 else [],
            "source_repository": f"https://github.com/{GITHUB_REPOSITORY}",
            "message": (
                "Educational source retrieval only. Symptom overlap does not "
                "establish a diagnosis. Treatment material is reproduced from "
                "the cited classical source and is not a personalized prescription."
            )
        }), 200

    except Exception:
        # Full traceback goes to Render logs; do not return HTML or leak stack traces.
        app.logger.exception("POST /api/search failed")
        return jsonify({
            "error": "The server could not complete the symptom search.",
            "hint": "Open /api/health and inspect the Render service logs for the traceback."
        }), 500


@app.errorhandler(404)
def not_found(_error):
    return jsonify({"error": "API route or page not found.", "path": request.path}), 404


@app.errorhandler(405)
def method_not_allowed(_error):
    return jsonify({
        "error": "HTTP method not allowed for this endpoint.",
        "path": request.path,
        "method": request.method
    }), 405


@app.errorhandler(HTTPException)
def handle_http_exception(error):
    return jsonify({
        "error": error.name,
        "message": error.description,
        "path": request.path
    }), error.code


@app.errorhandler(Exception)
def handle_unexpected_exception(error):
    app.logger.exception("Unhandled application exception: %s", error)
    return jsonify({
        "error": "Unexpected server error.",
        "hint": "Check the Render service logs for the full traceback."
    }), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", os.getenv("FLASK_PORT", "5000"))),
        debug=False
    )
