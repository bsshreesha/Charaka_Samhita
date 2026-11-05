"""Schema-aware parser for the Charaka Samhita chapter JSON files.

The parser uses the repository folder path as the authoritative Sthana/Adhyaya
source and preserves the original content-block order and indices.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath
from typing import Any

STHANAS = {"Chikitsa Sthana", "Nidana Sthana", "Sutra Sthana"}
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
IAST_RE = re.compile(r"[āīūṛṝḷḹṃṁḥṅñṭḍṇśṣ]")
VERSE_MARKER_RE = re.compile(r"(?:\|\||\|)\s*[\d०-९]", re.UNICODE)

def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " ".join(clean_text(v) for v in value if clean_text(v))
    if isinstance(value, dict):
        if "text" in value:
            return clean_text(value.get("text"))
        return " ".join(clean_text(v) for v in value.values() if v is not None)
    return ""

def normalize(value: str) -> str:
    # Preserve Devanagari vowel signs; stripping all combining marks corrupts Sanskrit.
    value = unicodedata.normalize("NFKC", value or "").lower()
    chars = []
    previous_script = ""
    for ch in value:
        code = ord(ch)
        is_devanagari = 0x0900 <= code <= 0x097F
        if unicodedata.combining(ch) and not is_devanagari and previous_script != "devanagari":
            continue
        chars.append(ch)
        if is_devanagari:
            previous_script = "devanagari"
        elif not unicodedata.combining(ch):
            previous_script = "latin" if ch.isascii() else ""
    value = "".join(chars)
    value = re.sub(r"[^a-z0-9\u0900-\u097f]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def flatten_table(block: dict) -> str:
    """Flatten table text for search while retaining full structure separately."""
    rows = block.get("rows") or []
    rendered = []
    for row in rows:
        cells = []
        for cell in row if isinstance(row, list) else []:
            if isinstance(cell, dict):
                cells.append(clean_text(cell.get("text", "")))
            else:
                cells.append(clean_text(cell))
        if cells:
            rendered.append(" | ".join(cells))
    return "\n".join(rendered)

def block_text(block: dict) -> str:
    typ = block.get("type", "")
    if typ == "table":
        return flatten_table(block)
    if typ in {"ul", "ol"}:
        items = block.get("items") or []
        if items:
            return " | ".join(clean_text(item) for item in items)
    return clean_text(block.get("text", ""))

def block_kind(text: str) -> str:
    if not text:
        return "empty"
    if DEVANAGARI_RE.search(text):
        return "sanskrit"
    if IAST_RE.search(text):
        return "transliteration"
    # Some files contain ASCII transliteration variants without diacritics.
    if VERSE_MARKER_RE.search(text) and re.search(r"[a-zA-Z]", text):
        return "transliteration"
    return "english_or_other"

def source_metadata(path: str) -> tuple[str, str]:
    parts = PurePosixPath(path).parts
    sthana = parts[0] if len(parts) >= 3 and parts[0] in STHANAS else "Unknown"
    adhyaya_folder = parts[1] if len(parts) >= 3 else "Unknown"
    # Preserve numbered directory name, since it disambiguates chapters.
    return sthana, adhyaya_folder

def parse_chapter(document: dict, relative_path: str) -> list[dict]:
    if not isinstance(document, dict):
        raise ValueError(f"{relative_path}: JSON root must be an object")
    content = document.get("content")
    if not isinstance(content, list):
        raise ValueError(f"{relative_path}: missing content[] array")

    sthana, adhyaya_folder = source_metadata(relative_path)
    chapter_name = clean_text(document.get("chapter")) or adhyaya_folder
    blocks = []
    heading_stack: list[str] = []
    for idx, raw in enumerate(content):
        if not isinstance(raw, dict):
            continue
        typ = clean_text(raw.get("type")).lower()
        txt = block_text(raw)
        level = raw.get("level")
        if typ in {"h1", "h2", "h3", "h4", "h5", "h6"} and txt:
            try:
                n = int(level or typ[1])
            except (TypeError, ValueError):
                n = int(typ[1])
            heading_stack = heading_stack[:max(0, n - 1)]
            heading_stack.append(txt)
        blocks.append({
            "index": idx,
            "type": typ,
            "text": txt,
            "items": raw.get("items") if typ in {"ul", "ol"} else None,
            "rows": raw.get("rows") if typ == "table" else None,
            "headings": heading_stack.copy(),
            "kind": block_kind(txt) if typ in {"p", "li", "blockquote", "pre"} else typ,
        })

    # Build one retrieval unit for each contiguous Sanskrit verse passage.
    # Source sequence in this repository commonly appears as:
    # Sanskrit paragraphs -> IAST transliteration -> ASCII transliteration -> English.
    passages = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b["kind"] != "sanskrit" or b["type"] not in {"p", "li", "blockquote"}:
            i += 1
            continue

        sanskrit_blocks = [b]
        j = i + 1
        while j < len(blocks):
            nxt = blocks[j]
            if nxt["kind"] == "sanskrit" and nxt["type"] in {"p", "li", "blockquote"}:
                sanskrit_blocks.append(nxt)
                j += 1
                continue
            break

        # Capture following transliteration paragraphs, then the first relevant
        # English translation/explanation before the next heading/verse group.
        translit_blocks = []
        english_blocks = []
        k = j
        while k < len(blocks):
            nxt = blocks[k]
            if nxt["type"] in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                break
            if nxt["kind"] == "sanskrit":
                break
            if nxt["kind"] == "transliteration" and nxt["type"] in {"p", "li"}:
                translit_blocks.append(nxt)
            elif nxt["kind"] == "english_or_other" and nxt["type"] in {"p", "li", "blockquote"}:
                # Keep first translation/explanation paragraph; stop at a new
                # Sanskrit sequence. A few nearby paragraphs may be commentary.
                english_blocks.append(nxt)
                if len(english_blocks) >= 2:
                    break
            elif nxt["type"] not in {"p", "li", "blockquote"}:
                if translit_blocks or english_blocks:
                    break
            k += 1

        verse_text = "\n".join(x["text"] for x in sanskrit_blocks if x["text"])
        transliteration = "\n".join(x["text"] for x in translit_blocks if x["text"])
        translation = "\n\n".join(x["text"] for x in english_blocks if x["text"])
        headings = sanskrit_blocks[0]["headings"]
        context = " > ".join(headings[1:] if len(headings) > 1 else headings)
        # Include the heading and translation in search text, but never fabricate
        # a verse or translation when the source does not contain one.
        search_text = " ".join([context, verse_text, transliteration, translation])
        passages.append({
            "source": clean_text(document.get("source")) or "Charaka Samhita",
            "sthana": sthana,
            "adhyaya_folder": adhyaya_folder,
            "chapter": chapter_name,
            "context": context,
            "headings": headings,
            "shloka": verse_text,
            "transliteration": transliteration,
            "translation": translation,
            "source_file": relative_path,
            "source_url": clean_text(document.get("url")),
            "block_index": b["index"],
            "block_end_index": sanskrit_blocks[-1]["index"],
            "translation_block_indices": [x["index"] for x in english_blocks],
            "search_text": search_text,
        })
        i = max(j, i + 1)

    # Also index non-verse source paragraphs, e.g. English diagnostic explanations
    # and tables, so symptom evidence can be discovered even where no shloka is
    # structurally paired. They are explicitly labelled as source passages.
    for b in blocks:
        if b["type"] not in {"p", "li", "blockquote", "ul", "ol", "table"} or not b["text"]:
            continue
        if b["kind"] == "sanskrit":
            continue
        if b["kind"] == "transliteration":
            continue
        passages.append({
            "source": clean_text(document.get("source")) or "Charaka Samhita",
            "sthana": sthana,
            "adhyaya_folder": adhyaya_folder,
            "chapter": chapter_name,
            "context": " > ".join(b["headings"]),
            "headings": b["headings"],
            "shloka": "",
            "transliteration": "",
            "translation": b["text"],
            "source_file": relative_path,
            "source_url": clean_text(document.get("url")),
            "block_index": b["index"],
            "block_end_index": b["index"],
            "translation_block_indices": [b["index"]],
            "search_text": " ".join([" > ".join(b["headings"]), b["text"]]),
            "passage_type": "source_explanation",
        })

    return passages
