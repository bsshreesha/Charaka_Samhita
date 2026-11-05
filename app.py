"""
Charaka Samhita Practitioner Reference — Flask application entry point.

The application performs source-grounded retrieval only. It does not diagnose,
rank clinical probabilities, or generate treatment recommendations.

Render:
    Build: pip install -r requirements.txt && python build_index.py
    Start: gunicorn app:app --bind 0.0.0.0:$PORT
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from charaka_backend.config import GITHUB_BRANCH, GITHUB_REPOSITORY
from charaka_backend.repository import build_index, load_index
from charaka_backend.search import search_passages


# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config.update(
    JSON_AS_ASCII=False,
    MAX_CONTENT_LENGTH=64 * 1024,  # 64 KB is ample for a symptom query.
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
app.logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

_INDEX_LOCK = threading.Lock()
MAX_SYMPTOMS = 40
MAX_SYMPTOM_LENGTH = 300
DEFAULT_RESULT_LIMIT = 25
MAX_RESULT_LIMIT = 100


def _read_index() -> dict[str, Any] | None:
    """Read the persisted index without triggering network activity."""
    index = load_index()
    if not isinstance(index, dict):
        return None
    passages = index.get("passages")
    if not isinstance(passages, list):
        return None
    return index


def get_current_index() -> dict[str, Any]:
    """
    Return a valid index.

    The index is normally created by build_index.py during the Render build.
    A guarded lazy build is retained for local development and recovery when
    the index is absent. Concurrent first requests cannot build it twice.
    """
    index = _read_index()
    if index is not None:
        return index

    with _INDEX_LOCK:
        # Another request may have completed the build while this request
        # waited for the lock.
        index = _read_index()
        if index is not None:
            return index

        app.logger.warning("Search index is missing; starting a one-time build.")
        manifest = build_index(force=True)
        index = _read_index()

        if index is None:
            raise RuntimeError(
                "Index build returned, but data/index/passages.json is missing "
                "or invalid. Review the build logs and repository data."
            )

        failed = manifest.get("failed_chapters", []) if isinstance(manifest, dict) else []
        if failed:
            app.logger.warning(
                "Index built with %s failed chapter file(s).",
                len(failed),
            )
        return index


def _normalise_symptoms(value: Any) -> list[str]:
    """
    Accept either free text or a JSON array.

    Free text is split on commas, semicolons, newlines, and the conjunction
    'and'. A single phrase remains a single symptom entry.
    """
    if isinstance(value, str):
        items = re.split(
            r"[,;\n\r]+|\s+\band\b\s+",
            value,
            flags=re.IGNORECASE,
        )
    elif isinstance(value, list):
        items = value
    else:
        raise ValueError(
            "The 'symptoms' field must be free text or a list of text values."
        )

    cleaned: list[str] = []
    seen: set[str] = set()

    for item in items:
        if item is None:
            continue
        if not isinstance(item, (str, int, float)):
            raise ValueError("Each symptom must be a text value.")
        symptom = str(item).strip()
        if not symptom:
            continue
        if len(symptom) > MAX_SYMPTOM_LENGTH:
            raise ValueError(
                f"Each symptom must be {MAX_SYMPTOM_LENGTH} characters or fewer."
            )
        key = symptom.casefold()
        if key not in seen:
            cleaned.append(symptom)
            seen.add(key)

    if not cleaned:
        raise ValueError("Please enter at least one symptom.")
    if len(cleaned) > MAX_SYMPTOMS:
        raise ValueError(f"Enter no more than {MAX_SYMPTOMS} symptom items.")

    return cleaned


def _result_limit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = DEFAULT_RESULT_LIMIT
    return max(1, min(limit, MAX_RESULT_LIMIT))


def _error(message: str, status: int, **extra: Any):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


# ---------------------------------------------------------------------------
# Browser interface
# ---------------------------------------------------------------------------

@app.get("/")
def home():
    """Serve the Flask practitioner interface."""
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Service and index diagnostics
# ---------------------------------------------------------------------------

@app.get("/api")
@app.get("/api/")
def api_info():
    return jsonify({
        "service": "Charaka Samhita Practitioner Reference API",
        "status": "online",
        "repository": f"https://github.com/{GITHUB_REPOSITORY}",
        "branch": GITHUB_BRANCH,
        "endpoints": {
            "health": "GET /api/health",
            "symptoms": "GET /api/symptoms",
            "search": "POST /api/search",
            "rebuild": "POST /api/index/rebuild",
        },
        "search_example": {
            "method": "POST",
            "path": "/api/search",
            "json": {
                "symptoms": [
                    "fever",
                    "excessive thirst",
                    "burning sensation",
                    "loss of appetite",
                ],
                "limit": 25,
            },
        },
    })


@app.get("/api/health")
def health():
    """
    Lightweight diagnostic endpoint.

    Does not build/download the corpus. This makes it safe for Render health
    checks and clearly distinguishes an online service from a ready index.
    """
    try:
        index = _read_index()
        if index is None:
            return jsonify({
                "status": "degraded",
                "service": "Charaka Samhita Practitioner Reference API",
                "index_ready": False,
                "chapter_count": 0,
                "passage_count": 0,
                "failed_chapter_count": 0,
                "message": (
                    "Flask is running, but the search index is not ready. "
                    "Run python build_index.py during deployment."
                ),
                "repository": GITHUB_REPOSITORY,
                "branch": GITHUB_BRANCH,
            }), 503

        failed = index.get("failed_chapters", [])
        if not isinstance(failed, list):
            failed = []

        return jsonify({
            "status": "ok" if not failed else "degraded",
            "service": "Charaka Samhita Practitioner Reference API",
            "index_ready": True,
            "repository": GITHUB_REPOSITORY,
            "branch": GITHUB_BRANCH,
            "built_at": index.get("built_at"),
            "chapter_count": index.get("chapter_count", 0),
            "passage_count": len(index.get("passages", [])),
            "failed_chapter_count": len(failed),
            "failed_chapters": failed,
        }), 200

    except Exception:
        app.logger.exception("Health check failed.")
        return _error(
            "The health check could not read the search index.",
            500,
        )


@app.get("/api/symptoms")
def symptoms():
    """Return alias labels as optional suggestions; free-text search is allowed."""
    try:
        from charaka_backend.search import ALIASES
        return jsonify({
            "symptoms": sorted(ALIASES.keys()),
            "note": "Suggestions only. Practitioners may enter any symptom in free text.",
        }), 200
    except Exception:
        app.logger.exception("Could not load symptom suggestions.")
        return _error("Could not load symptom suggestions.", 500)


# ---------------------------------------------------------------------------
# Symptom search
# ---------------------------------------------------------------------------

@app.route("/api/search", methods=["GET", "POST"])
def search():
    """
    GET documents the endpoint.
    POST accepts {"symptoms": "free text"} or {"symptoms": ["...", "..."]}.
    """
    if request.method == "GET":
        return jsonify({
            "service": "Charaka Samhita Practitioner Reference API",
            "endpoint": "/api/search",
            "method": "POST",
            "content_type": "application/json",
            "example": {
                "symptoms": (
                    "intermittent fever, excessive thirst, "
                    "burning sensation, reduced appetite"
                ),
                "limit": 25,
            },
            "instruction": (
                "Use the homepage for the practitioner interface, or send "
                "a POST request with a JSON symptoms field."
            ),
        }), 200

    if not request.is_json:
        return _error(
            "Content-Type must be application/json.",
            415,
            example={"symptoms": "fever, thirst, burning sensation"},
        )

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _error(
            "The request body must be a JSON object.",
            400,
            example={"symptoms": ["fever", "excessive thirst"]},
        )

    try:
        symptom_list = _normalise_symptoms(payload.get("symptoms", ""))
    except ValueError as exc:
        return _error(str(exc), 400)

    limit = _result_limit(payload.get("limit", DEFAULT_RESULT_LIMIT))

    try:
        index = get_current_index()
        passages = index.get("passages", [])

        if not passages:
            return _error(
                "The source index contains no searchable passages.",
                503,
                hint="Review the build_index.py output and failed chapter list.",
            )

        results = search_passages(
            passages=passages,
            symptoms=symptom_list,
            limit=limit,
        )

        primary = results[0] if results else None
        additional = results[1:] if len(results) > 1 else []

        return jsonify({
            "status": "ok",
            "query": {"symptoms": symptom_list},
            "result_count": len(results),
            "results": results,
            "primary_reference": primary,
            "other_probable_diseases": additional,
            "source_repository": f"https://github.com/{GITHUB_REPOSITORY}",
            "message": (
                "Educational source retrieval only. Textual overlap does not "
                "establish a diagnosis. Treatment passages, when present, are "
                "historical source material and are not personalized prescriptions."
            ),
        }), 200

    except Exception:
        # Keep the detailed traceback in Render logs, while the browser always
        # receives JSON instead of an HTML error page.
        app.logger.exception("POST /api/search failed.")
        return _error(
            "The server could not complete the source search.",
            500,
            hint=(
                "Open /api/health and inspect the Render service logs for "
                "the detailed error."
            ),
        )


# ---------------------------------------------------------------------------
# Index rebuild
# ---------------------------------------------------------------------------

@app.post("/api/index/rebuild")
def rebuild_index_endpoint():
    """
    Manually rebuild the source index.

    Prefer the Render build command for normal deployments. This endpoint is
    provided for controlled maintenance and reports partial chapter failures.
    """
    try:
        with _INDEX_LOCK:
            manifest = build_index(force=True)

        failed = manifest.get("failed_chapters", [])
        return jsonify({
            "status": "built" if not failed else "built_with_warnings",
            "manifest": manifest,
            "message": (
                "Index build completed."
                if not failed
                else "Index build completed, but one or more chapter files failed."
            ),
        }), 200

    except Exception:
        app.logger.exception("Manual index rebuild failed.")
        return _error(
            "Index rebuild failed. Review the Render service logs.",
            500,
        )


# ---------------------------------------------------------------------------
# Consistent JSON error responses
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return _error("API endpoint not found.", 404, path=request.path)
    return render_template("index.html"), 200


@app.errorhandler(HTTPException)
def handle_http_exception(error: HTTPException):
    return _error(
        error.description or error.name,
        error.code or 500,
        name=error.name,
        path=request.path,
        method=request.method,
    )


@app.errorhandler(Exception)
def handle_unexpected_exception(error: Exception):
    app.logger.exception("Unhandled application exception: %s", error)
    return _error(
        "An unexpected server error occurred.",
        500,
        hint="Check the Render service logs for the full traceback.",
    )


# ---------------------------------------------------------------------------
# Local development entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", os.getenv("FLASK_PORT", "5000"))),
        debug=False,
    )
