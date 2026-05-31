import hashlib
from datetime import datetime
from pathlib import Path

import pandas as pd

from config.settings import (
    RAW_REGISTRY_DIR,
    RAW_DOCUMENTS_DIR,
    INTERIM_DIR,
    PROCESSED_DIR,
    LOGS_DIR,
    REPORTS_DIR,
)


def ensure_directories():
    for folder in [
        RAW_REGISTRY_DIR,
        RAW_DOCUMENTS_DIR,
        INTERIM_DIR,
        PROCESSED_DIR,
        LOGS_DIR,
        REPORTS_DIR,
    ]:
        folder.mkdir(parents=True, exist_ok=True)


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def make_run_log_path():
    return LOGS_DIR / f"{today_str()}_run.log"


def append_log(message: str):
    log_path = make_run_log_path()
    line = f"[{now_str()}] {message}\n"

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)

    print(line, end="")


def file_md5(file_path: Path) -> str:
    if not file_path.exists():
        return ""
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            md5.update(chunk)
    return md5.hexdigest()


def safe_read_csv(path: Path) -> pd.DataFrame:
    try:
        if path.exists():
            return pd.read_csv(path)
    except Exception:
        pass
    return pd.DataFrame()