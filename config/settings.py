from pathlib import Path

# =========================================================
# THƯ MỤC GỐC
# =========================================================
BASE_DIR = Path(__file__).resolve().parent.parent

CONFIG_DIR = BASE_DIR / "config"
SRC_DIR = BASE_DIR / "src"
DATA_DIR = BASE_DIR / "data"

RAW_DIR = DATA_DIR / "raw"
RAW_REGISTRY_DIR = RAW_DIR / "registry"
RAW_DOCUMENTS_DIR = RAW_DIR / "documents"

INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"

LOGS_DIR = BASE_DIR / "logs"
REPORTS_DIR = BASE_DIR / "reports" / "update_history"

# =========================================================
# FILE CHÍNH
# =========================================================
DOCUMENT_REGISTRY_FILE = RAW_REGISTRY_DIR / "document_registry.csv"
DOCUMENT_REGISTRY_SEED_FILE = RAW_REGISTRY_DIR / "document_registry_seed.csv"

PARSED_DOCUMENTS_FILE = INTERIM_DIR / "parsed_documents.csv"
DOCUMENT_COMPLETENESS_FILE = INTERIM_DIR / "document_completeness.csv"

EVENT_FEATURES_FILE = PROCESSED_DIR / "event_features.csv"
DAILY_PANEL_FILE = PROCESSED_DIR / "daily_panel.csv"
DATASET_MANIFEST_FILE = PROCESSED_DIR / "dataset_manifest.csv"

# =========================================================
# SOURCE
# =========================================================
BASE_SITE = "https://thuvienphapluat.vn"
SEARCH_BASE_URL = "https://thuvienphapluat.vn/page/tim-van-ban.aspx"
# =========================================================
# FETCH CONFIG
# =========================================================
TIMEOUT = 30
REQUEST_SLEEP = 1.0

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
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Referer": BASE_SITE + "/",
}