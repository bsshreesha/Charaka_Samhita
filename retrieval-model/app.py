from flask import Flask, jsonify, request, render_template
from flask_cors import CORS

from charaka_backend.config import GITHUB_REPOSITORY, GITHUB_BRANCH
from charaka_backend.repository import build_index, load_index
from charaka_backend.search import search_passages

app = Flask(__name__)
CORS(app)

def current_index():
    index = load_index()
    if index is None:
        manifest = build_index()
        index = load_index()
        if index is None:
            raise RuntimeError("Index build completed but index file could not be loaded.")
    return index

@app.get("/")
def home():
    return render_template("index.html")

@app.get("/api/health")
def health():
    index = load_index()
    return jsonify({
        "status": "ok",
        "repository": GITHUB_REPOSITORY,
        "branch": GITHUB_BRANCH,
        "index_ready": index is not None,
        "chapter_count": index.get("chapter_count", 0) if index else 0,
        "failed_chapters": index.get("failed_chapters", []) if index else [],
    })

@app.post("/api/index/rebuild")
def rebuild_index():
    try:
        manifest = build_index(force=True)
        return jsonify({"status": "built", "manifest": manifest})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502

@app.get("/api/symptoms")
def symptoms():
    from charaka_backend.search import ALIASES
    return jsonify({"symptoms": sorted(ALIASES.keys())})

@app.post("/api/search")
def search():
    payload = request.get_json(silent=True) or {}
    symptoms = payload.get("symptoms", [])
    if isinstance(symptoms, str):
        # Free-text entry: allow as many symptoms as the practitioner wishes.
        import re
        symptoms = [x.strip() for x in re.split(r"[,;\n\r]+|\s+\band\b\s+", symptoms, flags=re.IGNORECASE) if x.strip()]
    if not isinstance(symptoms, list):
        return jsonify({"error": "Enter symptoms as free text or a list of text items."}), 400
    symptoms = [str(s).strip() for s in symptoms if str(s).strip()]
    if not symptoms:
        return jsonify({"error": "Please enter at least one symptom."}), 400
    try:
        index = current_index()
        limit = payload.get("limit", 25)
        try:
            limit = max(1, min(int(limit), 100))
        except (TypeError, ValueError):
            limit = 25
        results = search_passages(index.get("passages", []), symptoms, limit)
        return jsonify({
            "query": {"symptoms": symptoms},
            "result_count": len(results),
            "results": results,
            "primary_reference": results[0] if results else None,
            "other_probable_diseases": results[1:] if len(results) > 1 else [],
            "source_repository": f"https://github.com/{GITHUB_REPOSITORY}",
            "message": "Educational source retrieval only. Symptom overlap does not establish a diagnosis; treatment material is reproduced from the cited classical source and is not a personalized prescription."
        })
    except Exception as exc:
        app.logger.exception("Search failed")
        return jsonify({"error": str(exc)}), 500

if __name__ == "__main__":
    from charaka_backend.config import PROJECT_ROOT
    import os
    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "true").lower() == "true",
    )
