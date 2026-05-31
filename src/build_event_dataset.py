import pandas as pd

from config.settings import PARSED_DOCUMENTS_FILE, EVENT_FEATURES_FILE
from src.utils import append_log, ensure_directories, safe_read_csv


EVENT_COLUMNS = [
    "event_date",
    "doc_id",
    "fuel_type",
    "base_price",
    "bog_contribution",
    "bog_spending",
    "retail_price",
    "unit",
    "source_url",
]


def build_event_dataset():
    ensure_directories()

    parsed_df = safe_read_csv(PARSED_DOCUMENTS_FILE)

    if parsed_df.empty:
        append_log("BUILD_EVENT: parsed_documents empty → write empty event_features")
        pd.DataFrame(columns=EVENT_COLUMNS).to_csv(
            EVENT_FEATURES_FILE, index=False, encoding="utf-8-sig"
        )
        append_log("BUILD_EVENT: event_features.csv saved")
        return

    event_df = pd.DataFrame(columns=EVENT_COLUMNS)

    event_df.to_csv(EVENT_FEATURES_FILE, index=False, encoding="utf-8-sig")
    append_log(f"BUILD_EVENT: rows = {len(event_df)}")
    append_log("BUILD_EVENT: event_features.csv saved")


if __name__ == "__main__":
    build_event_dataset()