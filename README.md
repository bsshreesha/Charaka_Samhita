# Charaka Samhita — Symptom-First Flask Backend

This backend searches the public repository `bsshreesha/Charaka_Samhita`.
The practitioner submits symptoms only. The backend discovers the Sthana and
Adhyaya from the actual JSON file path and returns source-linked references.

## 1. Architecture

```text
charaka_flask_backend/
├── app.py
├── build_index.py
├── requirements.txt
├── .env.example
├── charaka_backend/
│   ├── __init__.py
│   ├── config.py
│   ├── parser.py
│   ├── repository.py
│   └── search.py
└── data/
    ├── raw/       # downloaded original chapter JSON files (created at runtime)
    └── index/     # parsed search index (created at runtime)
```

The backend uses `.json` as its canonical data source. `.html` and `.txt` are
not merged into the search corpus, preventing duplicate or conflicting results.
They remain useful for manual verification.

## 2. Windows setup (PowerShell)

Open PowerShell in this project folder:

```powershell
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```

## 3. Build the repository index

```powershell
python build_index.py
```

The first run downloads the chapter JSON files under the three repository folders,
parses them and saves a local index. This may take a few minutes depending on
network speed and GitHub rate limits.

The command reports chapter count, passage count and any failed files. Do not
treat the index as complete if `Failed chapters` is greater than zero.

## 4. Start Flask

```powershell
python app.py
```

API base URL:

```text
http://127.0.0.1:5000
```

## 5. API endpoints

### Health

```http
GET /api/health
```

### Available symptom terms

```http
GET /api/symptoms
```

### Symptom-first search

```http
POST /api/search
Content-Type: application/json
```

Request:

```json
{
  "symptoms": ["fever", "excessive thirst", "burning sensation"],
  "limit": 20
}
```

The response includes `shloka`, `transliteration`, `translation`, `context`,
`sthana`, `adhyaya_folder`, `chapter`, `source_file`, `source_url`,
`block_index`, and matched symptom evidence.

### Rebuild the cached index

```http
POST /api/index/rebuild
```

## 6. Parser rules

- Uses the actual directory path to assign Sthana and Adhyaya.
- Preserves JSON content order and original block indices.
- Maintains heading context (`h1`–`h6`).
- Reads paragraphs, lists, blockquotes and complete table rows.
- Detects Devanagari text as Sanskrit.
- Detects IAST diacritics and verse-marked roman text as transliteration.
- Pairs adjacent source blocks conservatively; it does not invent missing
  Sanskrit, transliteration or translation.
- Also indexes English explanation blocks separately so symptom evidence can
  be found even when no verse pairing is available.

## 7. Important limitations

This is a first working retrieval backend, not a validated clinical decision
support system. Symptom matching is lexical and depends on the configured
terminology variants. It does not establish a diagnosis, assess severity, or
prescribe medicines. A practitioner must verify every source passage and its
clinical applicability.

Before deployment, add authentication, rate limiting, HTTPS, structured
logging, cache refresh controls and tests for every chapter's verse grouping.
Do not expose `/api/index/rebuild` publicly without administrator protection.


## Practitioner interface update

The home page (`http://127.0.0.1:5000/`) accepts unrestricted free-text symptom descriptions. Enter one or many symptoms in your own wording; separate them with commas or new lines when convenient. The search API also accepts a single free-text `symptoms` string.

Search results are grouped into an integrated learning card containing available Sanskrit shloka, transliteration, source translation/understanding, and treatment material from a corresponding Chikitsa Sthana chapter when the repository contains a matching chapter. Additional chapter overlaps appear separately as references to review. Missing source content is not generated. Rebuild the index after updating the parser: `python build_index.py`.
