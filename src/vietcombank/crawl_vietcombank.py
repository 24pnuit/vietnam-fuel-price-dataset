import os
import time
import requests
import pandas as pd

# =========================================================
# CONFIG
# =========================================================

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))

RAW_DIR = os.path.join(_ROOT, "data", "raw")
os.makedirs(RAW_DIR, exist_ok=True)

DATA_FILE = os.path.join(RAW_DIR, "vietcombank_usd_daily.csv")

BASE_URL = "https://www.vietcombank.com.vn/api/exchangerates"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.vietcombank.com.vn/vi-VN/KHCN/Cong-cu-Tien-ich/Ty-gia"
}

INITIAL_START_DATE = "2018-05-01"   # lần đầu backfill từ ngày này
BUFFER_DAYS = 7                     # mỗi lần update sẽ lùi lại 7 ngày để vá dữ liệu
REQUEST_SLEEP = 0.2                 # nghỉ nhẹ giữa các request
MAX_RETRIES = 3                     # số lần thử lại nếu request lỗi

# =========================================================
# LẤY DỮ LIỆU MỘT NGÀY
# =========================================================
 
def fetch_usd_by_date(date_str: str) -> dict:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                BASE_URL,
                params={"date": date_str},
                headers=HEADERS,
                timeout=20
            )
            resp.raise_for_status()
 
            data_json = resp.json()
            items     = data_json.get("Data", [])
            usd_item  = next(
                (i for i in items if str(i.get("currencyCode", "")).strip().upper() == "USD"),
                None
            )
 
            if usd_item is None:
                return {"query_date": date_str, "currency_code": None, "currency_name": None, "cash_buy": None, "transfer_buy": None, "sell": None, "status": "no_usd"} 
            return {
                "query_date":    date_str,
                "currency_code": usd_item.get("currencyCode"),
                "currency_name": usd_item.get("currencyName"),
                "cash_buy":      usd_item.get("cash"),
                "transfer_buy":  usd_item.get("transfer"),
                "sell":          usd_item.get("sell"),
                "status":        "success"
            }
 
        except Exception as e:
            if attempt == MAX_RETRIES:
                return {"query_date": date_str, "currency_code": None, "currency_name": None, "cash_buy": None, "transfer_buy": None, "sell": None, "status": f"error: {e}"}
            time.sleep(0.5 * attempt)
 
 
# =========================================================
# XÁC ĐỊNH NGÀY BẮT ĐẦU
# =========================================================
 
def determine_start_date() -> str:
    if not os.path.exists(DATA_FILE):
        return INITIAL_START_DATE
 
    df = pd.read_csv(DATA_FILE)
    if df.empty or "query_date" not in df.columns:
        return INITIAL_START_DATE
 
    max_date = pd.to_datetime(df["query_date"], errors="coerce").max()
    if pd.isna(max_date):
        return INITIAL_START_DATE
 
    return (max_date - pd.Timedelta(days=BUFFER_DAYS)).strftime("%Y-%m-%d")
 
 
# =========================================================
# CHẠY CHÍNH
# =========================================================
 
def main(start_date: str = None, end_date: str = None):
    os.makedirs(RAW_DIR, exist_ok=True)
 
    if start_date is None:
        start_date = determine_start_date()
    if end_date is None:
        end_date = pd.Timestamp.today().strftime("%Y-%m-%d")
 
    print(f"Crawl từ {start_date} → {end_date}")
    dates = pd.date_range(start=start_date, end=end_date, freq="D")
 
    new_records = []
    for i, d in enumerate(dates, 1):
        date_str = d.strftime("%Y-%m-%d")
        row = fetch_usd_by_date(date_str)
        new_records.append(row)
        print(f"  [{i}/{len(dates)}] {date_str} → {row['status']}")
        time.sleep(REQUEST_SLEEP)
 
    new_df = pd.DataFrame(new_records)
    for col in ["cash_buy", "transfer_buy", "sell"]:
        new_df[col] = pd.to_numeric(new_df[col], errors="coerce")
 
    # Gộp với dữ liệu cũ nếu có
    if os.path.exists(DATA_FILE):
        old_df = pd.read_csv(DATA_FILE)
        combined = pd.concat([old_df, new_df], ignore_index=True)
    else:
        combined = new_df.copy()
 
    # Giữ dòng mới nhất cho mỗi ngày rồi sắp xếp
    combined["query_date"] = pd.to_datetime(combined["query_date"], errors="coerce")
    combined = (
        combined
        .drop_duplicates(subset=["query_date"], keep="last")
        .sort_values("query_date")
        .reset_index(drop=True)
    )
 
    combined.to_csv(DATA_FILE, index=False, encoding="utf-8-sig")
 
    ok  = (new_df["status"] == "success").sum()
    err = new_df["status"].astype(str).str.startswith("error").sum()
    print(f"\nXong. Thành công: {ok} | Lỗi: {err} | File: {DATA_FILE}")

if __name__ == "__main__":
    main()