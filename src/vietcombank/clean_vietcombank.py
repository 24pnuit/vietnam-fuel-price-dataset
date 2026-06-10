import re
import os
import pandas as pd

# ── CONFIG PATHS ──────────────────────────────────────────────────────────────
_HERE       = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.getcwd()
_ROOT       = os.path.abspath(os.path.join(_HERE, "..", ".."))

RAW_PATH    = os.path.join(_ROOT, "data", "raw", "vietcombank_usd_daily.csv")
OUTPUT_PATH = os.path.join(_ROOT, "data", "interim", "cleaned_vietcombank_usd_daily.csv")
START_DATE  = "2018-05-01"

os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)


def parse_sell_value(raw: str) -> float | None:
    if not isinstance(raw, str):
        raw = str(raw)
    cleaned = raw.replace(",", "").strip()
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return None if value < 0 else value


def clean_vietcombank_usd(
    raw_path: str = RAW_PATH,
    output_path: str = OUTPUT_PATH,
    start_date: str = START_DATE,
) -> pd.DataFrame:
    
    # ── 1. Load ───────────────────────────────────────────────────────────────
    df = pd.read_csv(raw_path, dtype=str)
    print("=" * 55)
    print("VIETCOMBANK USD DAILY — DATA CLEANING REPORT")
    print("=" * 55)
    print(f"Raw rows loaded        : {len(df):,}")

    # ── 2. Chuẩn hoá ngày ────────────────────────────────────────────────────
    df['date'] = pd.to_datetime(df['query_date'], format='%Y-%m-%d', errors='coerce')
    n_bad_dates = df['date'].isna().sum()
    print(f"Ngày parse lỗi (NaT)   : {n_bad_dates}")
    if n_bad_dates > 0:
        print("  → Các dòng lỗi ngày:")

    # ── 3. Lọc từ start_date ─────────────────────────────────────────────────
    df = df[df['date'] >= pd.Timestamp(start_date)].copy()
    print(f"Sau lọc từ {start_date}  : {len(df):,} dòng")

    # ── 4. Chỉ giữ dòng có giá ───────────────────────────────────────────────
    n_no_usd = (df['status'] == 'no_usd').sum()
    print(f"Dòng no_usd (bỏ qua)   : {n_no_usd:,}")
    df = df[df['status'] == 'success'].copy()
    print(f"Dòng có giá (success)  : {len(df):,}")

    # ── 5. Parse vcb_sell ─────────────────────────────────────────────────────
    df['vcb_sell'] = df['sell'].apply(parse_sell_value)

    n_null  = df['vcb_sell'].isna().sum()
    n_neg   = (df['sell'].str.replace(',', '', regex=False)
                          .str.strip()
                          .apply(lambda x: float(x) if re.match(r'^-?\d+\.?\d*$', x) else 0) < 0).sum()
    print(f"\n── Kiểm tra vcb_sell ──────────────────────────────")
    print(f"Null / parse lỗi       : {n_null}")
    print(f"Giá trị âm (đã loại)   : {n_neg}")
    if n_null > 0:
        print("  → Dòng bị null vcb_sell:")
        print(df[df['vcb_sell'].isna()][['date', 'sell']].to_string())

    # ── 6. Duplicate dates ────────────────────────────────────────────────────
    # File sắp xếp cũ → mới: keep='last' giữ dòng mới nhất
    n_dup = df['date'].duplicated(keep='last').sum()
    print(f"\nDuplicate dates (bỏ)   : {n_dup}")
    df = df.sort_values('date')
    df = df.drop_duplicates(subset='date', keep='last').reset_index(drop=True)

    # ── 7. Output ─────────────────────────────────────────────────────────────
    out = df[['date', 'vcb_sell']].copy()
    out['date'] = out['date'].dt.strftime('%d-%m-%Y')

    print(f"\n── Output ─────────────────────────────────────────")
    print(f"Tổng dòng output       : {len(out):,}")
    print(f"Khoảng ngày            : {out['date'].iloc[0]} → {out['date'].iloc[-1]}")

    out.to_csv(output_path, index=False)
    print(f"\n Đã lưu: {output_path}")
    return out


# ── UNIT TESTS ────────────────────────────────────────────────────────────────
def _run_unit_tests():
    print("\n── Unit tests parse_sell_value ────────────────────")
    cases = [
        ("23305.0",   23305.0),   # bình thường
        ("23,305.0",  23305.0),   # có dấu phẩy
        (" 23305 ",   23305.0),   # có khoảng trắng
        ("-100.0",    None),      # âm → None
        ("abc",       None),      # không phải số
        ("",          None),      # rỗng
    ]
    all_pass = True
    for raw, expected in cases:
        result = parse_sell_value(raw)
        status = "PASS" if result == expected else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  [{status}] parse_sell_value({raw!r:15}) = {result} (expected {expected})")
    print(f"{'Tất cả pass ✓' if all_pass else 'Có test FAIL ✗'}\n")


if __name__ == "__main__":
    _run_unit_tests()
    df_clean = clean_vietcombank_usd()