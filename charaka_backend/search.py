"""Symptom-first retrieval and educational grouping over indexed source passages.

All displayed Sanskrit, translation, explanation and treatment text is copied from
indexed source passages. This module does not infer a diagnosis or generate therapy.
"""
from __future__ import annotations
import re
from collections import defaultdict
from .parser import normalize

ALIASES = {
    "fever": ["fever", "jwara", "jvara", "ज्वर"],
    "burning sensation": ["burning sensation", "burning", "daha", "दाह"],
    "excessive thirst": ["excessive thirst", "thirst", "trishna", "trsna", "तृष्णा"],
    "cough": ["cough", "kasa", "kāsa", "कास"],
    "breathlessness": ["breathlessness", "dyspnoea", "dyspnea", "shwasa", "śvāsa", "श्वास"],
    "vomiting": ["vomiting", "emesis", "chhardi", "chardi", "छर्दि"],
    "diarrhoea": ["diarrhoea", "diarrhea", "atisara", "atisāra", "अतिसार"],
    "loss of appetite": ["loss of appetite", "poor appetite", "anorexia", "aruchi", "अरुचि"],
    "indigestion": ["indigestion", "ajirna", "ajeerna", "अजीर्ण"],
    "pain": ["pain", "shoola", "shula", "शूल"],
    "abdominal pain": ["abdominal pain", "stomach pain", "belly pain", "udarashoola"],
    "swelling": ["swelling", "oedema", "edema", "shotha", "शोथ"],
    "itching": ["itching", "pruritus", "kandu", "कण्डू"],
    "heaviness": ["heaviness", "gaurava", "गौरव"],
    "fatigue": ["fatigue", "lassitude", "alasya", "आलस्य"],
    "disturbed sleep": ["disturbed sleep", "insomnia", "nidranasha", "निद्रानाश"],
}

def expand_term(term: str) -> list[str]:
    key = normalize(term)
    if not key: return []
    for canonical, variants in ALIASES.items():
        all_terms = [canonical, *variants]
        if key == normalize(canonical) or key in {normalize(v) for v in variants}:
            return list(dict.fromkeys(normalize(v) for v in all_terms if normalize(v)))
    return [key]

def phrase_present(haystack: str, needle: str) -> bool:
    if not needle: return False
    if re.search(r"[a-z0-9]", needle):
        return re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", haystack) is not None
    return needle in haystack

def _chapter_key(row: dict) -> tuple[str, str]:
    return (row.get("sthana", "Unknown"), row.get("adhyaya_folder") or row.get("chapter", "Unknown"))

def _disease_key(folder: str) -> str:
    value = normalize(re.sub(r"^\s*\d+\s*", "", folder or ""))
    value = re.sub(r"\b(nidana|chikitsa|chikitsita|adhyaya|chapter)\b", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def _is_treatment(row: dict) -> bool:
    context = normalize(" ".join(row.get("headings", []) if isinstance(row.get("headings"), list) else [row.get("context", "")]))
    # Heading labels are source-derived. Never treat every Chikitsa passage as a prescription.
    return any(x in context for x in ("treatment", "management", "chikitsa", "therapy", "line of treatment", "therapeutic"))

def search_passages(passages: list[dict], symptoms: list[str], limit: int = 25) -> list[dict]:
    groups = [(s.strip(), expand_term(s)) for s in symptoms if normalize(s)]
    if not groups: return []
    matched_rows = []
    for p in passages:
        haystack = normalize(p.get("search_text", ""))
        matched, variants = [], {}
        for symptom, terms in groups:
            hits = [v for v in terms if phrase_present(haystack, v)]
            if hits:
                matched.append(symptom); variants[symptom] = hits[:5]
        if not matched: continue
        row = {k: v for k, v in p.items() if k != "search_text"}
        row["matched_symptoms"] = matched
        row["matched_terms"] = variants
        row["relevance_score"] = len(matched) * 10 + (4 if p.get("shloka") else 0)
        matched_rows.append(row)

    # Group evidence into one educational card per source chapter. Include a corresponding
    # Chikitsa chapter only when its normalized disease-name key exactly matches.
    by_chapter: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in matched_rows: by_chapter[_chapter_key(r)].append(r)
    all_by_disease: dict[str, list[dict]] = defaultdict(list)
    for p in passages:
        folder = p.get("adhyaya_folder") or p.get("chapter", "")
        all_by_disease[_disease_key(folder)].append(p)

    cards = []
    for (sthana, folder), evidence in by_chapter.items():
        evidence.sort(key=lambda x: (-x["relevance_score"], 0 if x.get("shloka") else 1, x.get("block_index", 0)))
        disease_key = _disease_key(folder)
        chapter_all = all_by_disease.get(disease_key, [])
        verse = next((x for x in evidence if x.get("shloka")), None)
        explanation_rows = [x for x in evidence if x.get("translation") and x is not verse]
        # If no explanation itself matched, use nearby chapter source explanations as context,
        # but only from the same chapter and only where available.
        if not explanation_rows:
            explanation_rows = [x for x in chapter_all if x.get("translation") and not x.get("shloka")][:2]
        treatment_candidates = [x for x in chapter_all if x.get("sthana") == "Chikitsa Sthana" and _is_treatment(x)]
        if not treatment_candidates:
            treatment_candidates = [x for x in chapter_all if x.get("sthana") == "Chikitsa Sthana" and x.get("translation")]
        treatment_rows = treatment_candidates[:3]
        cards.append({
            "title": (verse or evidence[0]).get("chapter") or folder,
            "sthana": sthana,
            "adhyaya_folder": folder,
            "matched_symptoms": sorted({s for x in evidence for s in x.get("matched_symptoms", [])}),
            "relevance_score": max(x["relevance_score"] for x in evidence),
            "shloka": (verse or {}).get("shloka", ""),
            "transliteration": (verse or {}).get("transliteration", ""),
            "understanding": (verse or {}).get("translation", "") or (explanation_rows[0].get("translation", "") if explanation_rows else ""),
            "supporting_explanations": [x.get("translation", "") for x in explanation_rows[:2] if x.get("translation")],
            "treatment_sources": [{"text": x.get("translation", ""), "shloka": x.get("shloka", ""), "transliteration": x.get("transliteration", ""), "sthana": x.get("sthana"), "chapter": x.get("chapter"), "source_file": x.get("source_file"), "source_url": x.get("source_url"), "block_index": x.get("block_index")} for x in treatment_rows if x.get("translation") or x.get("shloka")],
            "source_file": (verse or evidence[0]).get("source_file"),
            "source_url": (verse or evidence[0]).get("source_url"),
            "block_index": (verse or evidence[0]).get("block_index"),
            "evidence_count": len(evidence),
            "other_evidence": [{"text": x.get("translation", ""), "shloka": x.get("shloka", ""), "source_file": x.get("source_file"), "source_url": x.get("source_url"), "block_index": x.get("block_index")} for x in evidence[1:4]],
        })
    cards.sort(key=lambda x: (-len(x["matched_symptoms"]), -x["relevance_score"], x["title"]))
    return cards[:limit]
