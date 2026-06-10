from datetime import datetime
from pathlib import Path

import pandas as pd

from settings import (
    RAW_DIR,
    RAW_DOCUMENTS_DIR,
    INTERIM_DIR,
    LOGS_DIR,
)


def ensure_directories():
    for folder in [RAW_DIR, RAW_DOCUMENTS_DIR, INTERIM_DIR, LOGS_DIR]:
        folder.mkdir(parents=True, exist_ok=True)


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def append_log(message: str):
    log_path = LOGS_DIR / f"{today_str()}_run.log"
    line = f"[{now_str()}] {message}\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)
    print(line, end="")


def safe_read_csv(path: Path) -> pd.DataFrame:
    try:
        if path.exists():
            return pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        pass
    return pd.DataFrame()