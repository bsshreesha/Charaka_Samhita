import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "bsshreesha/Charaka_Samhita")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
GITHUB_API = "https://api.github.com"
RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/{GITHUB_BRANCH}"
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INDEX_DIR = DATA_DIR / "index"
INDEX_FILE = INDEX_DIR / "passages.json"
MANIFEST_FILE = INDEX_DIR / "manifest.json"
