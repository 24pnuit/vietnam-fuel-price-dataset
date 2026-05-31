import pandas as pd

from config.settings import EVENT_FEATURES_FILE, DAILY_PANEL_FILE
from src.utils import append_log, ensure_directories, safe_read_csv


DAILY_COLUMNS = [
    "date",
    "fuel_type",
    "base_price",
    "bog_contribution",
    "bog_spending",
    "retail_price",
]


def build_daily_dataset():
    ensure_directories()

    event_df = safe_read_csv(EVENT_FEATURES_FILE)

    if event_df.empty:
        append_log("BUILD_DAILY: event_features empty → write empty daily_panel")
        pd.DataFrame(columns=DAILY_COLUMNS).to_csv(
            DAILY_PANEL_FILE, index=False, encoding="utf-8-sig"
        )
        append_log("BUILD_DAILY: daily_panel.csv saved")
        return

    daily_df = pd.DataFrame(columns=DAILY_COLUMNS)

    daily_df.to_csv(DAILY_PANEL_FILE, index=False, encoding="utf-8-sig")
    append_log(f"BUILD_DAILY: rows = {len(daily_df)}")
    append_log("BUILD_DAILY: daily_panel.csv saved")


if __name__ == "__main__":
    build_daily_dataset()