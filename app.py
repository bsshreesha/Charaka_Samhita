from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import logging
import os
import re

from charaka_backend.config import GITHUB_REPOSITORY, GITHUB_BRANCH
from charaka_backend.repository import build_index, load_index
from charaka_backend.search import search_passages

app = Flask(__name__)
CORS(app)
app.logger.setLevel(logging.INFO)


def current_index():
    """Load the existing index; build it only if it is missing."""
    index = load_index()

    if index is None:
        app.logger.warning("Search index not found. Building it now.")
        build_index()
        index = load_index()

    if index is None:
        raise RuntimeError(
            "The search index is unavailable. Run the index build command "
            "during deployment and check the Render build logs."
        )

    return index


@app.get("/")
def home():
    # The templates/index.html file must exist in the templates folder.
    return render_template("index.html")


@app.get("/api/health")
def health():
    try:
        index = load_index()
        return jsonify({
            "status": "ok",
            "repository": GITHUB_REPOSITORY,
            "branch": GITHUB_BRANCH,
            "index_ready": index is not None,
            "chapter_count": index.get("chapter_count", 0) if index else 0,
            "failed_chapters": index.get("failed_chapters", []) if index else [],
        }), 200
    except Exception:
        app.logger.exception("Health check failed")
        return jsonify({"status": "error", "message": "Health check failed."}), 500


@app.post("/api/index/rebuild")
def rebuild_index():
    try:
        manifest = build_index(force=True)
        return jsonify({"status": "built", "manifest": manifest}), 200
    except Exception as exc:
        app.logger.exception("Index rebuild failed")
        return jsonify({"error": str(exc)}), 502


@app.get("/api/symptoms")
def symptoms():
    try:
        from charaka_backend.search import ALIASES
        return jsonify({"symptoms": sorted(ALIASES.keys())}), 200
    except Exception as exc:
        app.logger.exception("Could not load symptom terms")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/search", methods=["GET", "POST"])
def search():
    # Visiting this URL in a browser sends GET. Explain how to use the API
    # instead of returning an unhelpful 405 response.
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
                "or send a POST request with a JSON symptoms field to this endpoint."
            )
        }), 200

    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({
            "error": "Expected a JSON object.",
            "example": {"symptoms": ["fever", "thirst"]}
        }), 400

    symptoms = payload.get("symptoms", [])

    if isinstance(symptoms, str):
        # Allow free text containing many symptoms.
        symptoms = [
            item.strip()
            for item in re.split(
                r"[,;\\n\\r]+|\\s+\\band\\b\\s+",
                symptoms,
                flags=re.IGNORECASE
            )
            if item.strip()
        ]

    if not isinstance(symptoms, list):
        return jsonify({
            "error": "The symptoms field must be free text or a list of text items."
        }), 400

    symptoms = [str(item).strip() for item in symptoms if str(item).strip()]

    if not symptoms:
        return jsonify({"error": "Please enter at least one symptom."}), 400

    try:
        index = current_index()

        try:
            limit = max(1, min(int(payload.get("limit", 25)), 100))
        except (TypeError, ValueError):
            limit = 25

        results = search_passages(
            index.get("passages", []),
            symptoms,
            limit
        )

        return jsonify({
            "query": {"symptoms": symptoms},
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

    except Exception as exc:
        app.logger.exception("Symptom search failed")
        return jsonify({
            "error": "The symptom search could not be completed.",
            "details": str(exc)
        }), 500


if __name__ == "__main__":
    app.run(
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", os.getenv("FLASK_PORT", "5000"))),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true"
    )
