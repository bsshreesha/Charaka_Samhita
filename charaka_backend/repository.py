"""Download chapter JSON files from the configured public GitHub repository."""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import quote

import requests

from .config import (
    GITHUB_API, GITHUB_BRANCH, GITHUB_REPOSITORY,
    RAW_BASE, RAW_DIR, INDEX_DIR, INDEX_FILE, MANIFEST_FILE
)
from .parser import STHANAS, parse_chapter

SESSION = requests.Session()
SESSION.headers.update({
    "Accept": "application/vnd.github+json",
    "User-Agent": "Charaka-Symptom-Reference-App/1.0",
})

def fetch_tree() -> list[dict]:
    url = f"{GITHUB_API}/repos/{GITHUB_REPOSITORY}/git/trees/{GITHUB_BRANCH}?recursive=1"
    response = SESSION.get(url, timeout=45)
    response.raise_for_status()
    payload = response.json()
    if payload.get("truncated"):
        raise RuntimeError("GitHub returned a truncated repository tree; cannot safely build a complete index.")
    return payload.get("tree", [])

def is_chapter_json(path: str) -> bool:
    parts = path.split("/")
    return len(parts) == 3 and parts[0] in STHANAS and parts[2].lower().endswith(".json")

def download_json(relative_path: str) -> dict:
    local = RAW_DIR / relative_path
    if local.exists():
        try:
            return json.loads(local.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            local.unlink(missing_ok=True)
    encoded_path = "/".join(quote(part, safe="") for part in relative_path.split("/"))
    url = f"{RAW_BASE}/{encoded_path}"
    response = SESSION.get(url, timeout=60)
    response.raise_for_status()
    payload = response.json()
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload

def build_index(force: bool = False) -> dict:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    tree = fetch_tree()
    paths = sorted(item["path"] for item in tree if item.get("type") == "blob" and is_chapter_json(item["path"]))
    if not paths:
        raise RuntimeError("No chapter JSON files found under the three configured Sthana folders.")

    passages = []
    errors = []
    chapter_manifest = []
    for path in paths:
        try:
            doc = download_json(path)
            parsed = parse_chapter(doc, path)
            passages.extend(parsed)
            chapter_manifest.append({
                "path": path,
                "chapter": doc.get("chapter"),
                "blocks": len(doc.get("content", [])),
                "indexed_passages": len(parsed),
                "source_url": doc.get("url"),
            })
        except Exception as exc:
            errors.append({"path": path, "error": str(exc)})

    # Do not silently claim completeness if some source files failed.
    index_payload = {
        "repository": GITHUB_REPOSITORY,
        "branch": GITHUB_BRANCH,
        "built_at": int(time.time()),
        "chapter_count": len(chapter_manifest),
        "failed_chapters": errors,
        "passages": passages,
    }
    INDEX_FILE.write_text(json.dumps(index_payload, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "repository": GITHUB_REPOSITORY,
        "branch": GITHUB_BRANCH,
        "chapter_count": len(chapter_manifest),
        "passage_count": len(passages),
        "failed_chapters": errors,
        "chapters": chapter_manifest,
        "built_at": index_payload["built_at"],
    }
    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest

def load_index() -> dict | None:
    if not INDEX_FILE.exists():
        return None
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
