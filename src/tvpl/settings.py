from pathlib import Path

# ── Thư mục ──────────────────────────────────────────────────────────────────
# settings.py nằm ở: Test\src\tvpl\settings.py
# parent.parent      = Test\src       ← BASE_DIR
# parent.parent.parent = Test\

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

RAW_DIR           = DATA_DIR / "raw"
INTERIM_DIR       = DATA_DIR / "interim"
RAW_DOCUMENTS_DIR = RAW_DIR  / "documents"
LOGS_DIR          = BASE_DIR / "tvpl" / "logs"

# ── File chính ────────────────────────────────────────────────────────────────
DOCUMENT_REGISTRY_FILE = RAW_DIR      / "document_registry.csv"
PARSED_DOCUMENTS_FILE  = INTERIM_DIR  / "parsed_documents.csv"

# ── Nguồn ────────────────────────────────────────────────────────────────────
BASE_SITE       = "https://thuvienphapluat.vn"
SEARCH_BASE_URL = "https://thuvienphapluat.vn/page/tim-van-ban.aspx"

# ── Fetch config ──────────────────────────────────────────────────────────────
TIMEOUT       = 30
REQUEST_SLEEP = 1.5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control":             "no-cache",
    "Pragma":                    "no-cache",
    "Connection":                "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Referer":                   BASE_SITE + "/",
}