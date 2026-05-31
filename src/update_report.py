import pandas as pd
from datetime import datetime

from config.settings import (
    DOCUMENT_REGISTRY_FILE,
    EVENT_FEATURES_FILE,
    DAILY_PANEL_FILE,
    DATASET_MANIFEST_FILE,
)
from src.utils import REPORTS_DIR, append_log, ensure_directories, today_str, file_md5, safe_read_csv


def count_rows(file_path):
    df = safe_read_csv(file_path)
    return len(df)


def update_report():
    ensure_directories()

    registry_rows = count_rows(DOCUMENT_REGISTRY_FILE)
    event_rows = count_rows(EVENT_FEATURES_FILE)
    daily_rows = count_rows(DAILY_PANEL_FILE)

    manifest_row = pd.DataFrame([{
        "run_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "registry_rows": registry_rows,
        "event_rows": event_rows,
        "daily_rows": daily_rows,
        "registry_md5": file_md5(DOCUMENT_REGISTRY_FILE),
        "event_md5": file_md5(EVENT_FEATURES_FILE),
        "daily_md5": file_md5(DAILY_PANEL_FILE),
    }])

    old_df = safe_read_csv(DATASET_MANIFEST_FILE)
    if old_df.empty:
        manifest_df = manifest_row
    else:
        manifest_df = pd.concat([old_df, manifest_row], ignore_index=True)

    manifest_df.to_csv(DATASET_MANIFEST_FILE, index=False, encoding="utf-8-sig")

    report_path = REPORTS_DIR / f"update_{today_str()}.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"Run date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Registry rows: {registry_rows}\n")
        f.write(f"Event rows: {event_rows}\n")
        f.write(f"Daily rows: {daily_rows}\n")

    append_log(f"REPORT: update history saved -> {report_path}")
    append_log(f"REPORT: dataset manifest updated -> {DATASET_MANIFEST_FILE}")


if __name__ == "__main__":
    update_report()