import re
import os
import pandas as pd

# CONFIG PATHS
_HERE        = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.getcwd()
_ROOT        = os.path.abspath(os.path.join(_HERE, "..", ".."))

RAW_PATH     = os.path.join(_ROOT, "data", "interim", "parsed_bog_petrolimex.csv")
OUTPUT_PATH  = os.path.join(_ROOT, "data", "interim", "cleaned_bog_petrolimex.csv")
START_DATE   = "2018-05-01"

os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)


def parse_bog_value(raw: str) -> float | None:
    if not isinstance(raw, str):
        return None

    s = raw.strip()
    sign = 1

    if s.startswith("-") or "âm" in s.lower():
        sign = -1

    m = re.search(r"âm\s*\([+-]?\s*\)\s*([\d.,]+)", s, re.IGNORECASE)
    if m:
        return sign * _parse_number(m.group(1))

    m = re.search(r"âm\s*\(\s*-?\s*([\d.,]+)\s*\)", s, re.IGNORECASE)
    if m:
        return sign * _parse_number(m.group(1))

    if s.startswith("-"):
        m = re.search(r"-([\d.,]+)", s)
        if m:
            return sign * _parse_number(m.group(1))

    m = re.search(r"dương\s*\([+-]?\s*\)\s*([\d.,]+)", s, re.IGNORECASE)
    if m:
        return sign * _parse_number(m.group(1))

    m = re.search(r"dương\s*\(\s*\+?\s*([\d.,]+)\s*\)", s, re.IGNORECASE)
    if m:
        return sign * _parse_number(m.group(1))

    m = re.search(r"([\d.,]+)\s*tỷ", s, re.IGNORECASE)
    if m:
        return sign * _parse_number(m.group(1))

    return None


def _parse_number(num_str: str) -> float:
    s = num_str.strip()

    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts) == 2 and len(parts[1]) == 3:
            s = parts[0] + parts[1]
    elif "," in s:
        s = s.replace(",", ".")

    return float(s)


def clean_bog_petrolimex(
    raw_path: str = RAW_PATH,
    output_path: str = OUTPUT_PATH,
    start_date: str = START_DATE,
    verbose: bool = True,
) -> pd.DataFrame:

    # ── 1. Đọc file ───────────────────────────────────────────────────────────
    df = pd.read_csv(raw_path)
    if verbose:
        print(f"[1] Đọc file từ interim: {len(df)} dòng")

    # ── 2. Parse ngày & chuẩn hóa định dạng DD/MM/YYYY ───────────────────────
    df["date"] = pd.to_datetime(
        df["report_date"], format="mixed", dayfirst=True, errors="coerce"
    )
    n_date_fail = df["date"].isna().sum()
    if n_date_fail > 0:
        print(f"[!] CẢNH BÁO: {n_date_fail} dòng parse ngày thất bại")
    elif verbose:
        print(f"[2] Parse ngày: OK — {df['date'].min().date()} → {df['date'].max().date()}")

    # ── 3. Lọc từ start_date ──────────────────────────────────────────────────
    df = df[df["date"] >= start_date].copy()
    if verbose:
        print(f"[3] Lọc từ {start_date}: còn {len(df)} dòng")

    # ── 4. Parse & chuẩn hóa số tiền ─────────────────────────────────────────
    df["petrolimex_bog_ty_dong"] = df["bog_petrolimex"].apply(parse_bog_value)
    df["petrolimex_bog_ty_dong"] = pd.to_numeric(
        df["petrolimex_bog_ty_dong"], errors="coerce"
    )

    n_parse_fail = df["petrolimex_bog_ty_dong"].isna().sum()
    if n_parse_fail > 0:
        print(f"[!] CẢNH BÁO: {n_parse_fail} dòng parse BOG thất bại")
        print(df[df["petrolimex_bog_ty_dong"].isna()][["date", "bog_petrolimex"]].to_string())
    elif verbose:
        non_null = df["petrolimex_bog_ty_dong"].dropna()
        print(
            f"[4] Parse giá trị BOG: OK — {len(non_null)} giá trị số, "
            f"range [{non_null.min():.1f}, {non_null.max():.1f}] tỷ đồng"
        )

    # ── 5. Kiểm tra trùng ngày → giữ dòng cũ hơn ────────────────────────────────
    dup = df["date"].duplicated(keep="last")
    if dup.sum() > 0:
        print(f"[!] CẢNH BÁO: Phát hiện {dup.sum()} dòng trùng ngày → giữ dòng cuối cùng")
        df = df[~dup].copy()
        print(f"    → Còn {len(df)} dòng")
    elif verbose:
        print(f"[5] Kiểm tra trùng ngày: OK — không có trùng")

    # ── 6. Chọn cột output, sắp xếp & format ngày DD/MM/YYYY ─────────────────
    result = (
        df[["date", "petrolimex_bog_ty_dong"]]   
        .sort_values("date")
        .reset_index(drop=True)
    )
    result["date"] = result["date"].dt.strftime("%d/%m/%Y") 

    # ── 7. Lưu file ───────────────────────────────────────────────────────────
    result.to_csv(output_path, index=False)
    if verbose:
        print(f"[6] Lưu thành công: {output_path}")
        print(f"\n── Thống kê cuối ──────────────────────────────")
        print(f"   Số dòng          : {len(result)}")
        print(f"   Date range       : {result['date'].iloc[0]} → {result['date'].iloc[-1]}")
        non_null = result["petrolimex_bog_ty_dong"].dropna()
        print(f"   BOG min          : {non_null.min():.1f} tỷ đồng")
        print(f"   BOG max          : {non_null.max():.1f} tỷ đồng")
        print(f"   BOG mean         : {non_null.mean():.1f} tỷ đồng")
        print(f"   NaN              : {result['petrolimex_bog_ty_dong'].isna().sum()} dòng")
        print(f"───────────────────────────────────────────────")

    return result


def _run_unit_tests():
    import numpy as np

    tests = [
        ("1.074 tỷ đồng",           1074.0),
        ("0.473 tỷ đồng",            473.0),
        ("1.412,5 tỷ Đồng",         1412.5),
        ("928 tỷ đồng",              928.0),
        ("970 tỷđồng",               970.0),
        ("9,6 tỷđồng",                 9.6),
        ("dương (+) 3.167 tỷ đồng", 3167.0),
        ("dương (+) 917 tỷ đồng",    917.0),
        ("dương (53,3) tỷ đồng",      53.3),
        ("dương (305) tỷ đồng",      305.0),
        ("dương  (+) 1.308 tỷ đồng",1308.0),
        ("âm (-140) tỷ đồng",       -140.0),
        ("âm (- 49) tỷ đồng",        -49.0),
        ("âm (-108 ) tỷ đồng",      -108.0),
        ("âm (-148,5) tỷ đồng",     -148.5),
        ("âm (-193,5) tỷ đồng",     -193.5),
        ("âm (-) 197 tỷ đồng",      -197.0),
        ("âm (-) 216  tỷ đồng",     -216.0),
        ("-246 tỷđồng",             -246.0),
        ("-316 tỷđồng",             -316.0),
    ]

    print("── Unit tests parse_bog_value ──────────────────")
    all_pass = True
    for raw, expected in tests:
        result = parse_bog_value(raw)
        passed = result == expected
        status = "✓" if passed else "✗"
        if not passed:
            all_pass = False
        print(f"  {status}  {repr(raw):<42} → {result}")

    print("\n── Unit tests format ngày ──────────────────────")
    date_tests = [
        ("21.5.2026",  "21/05/2026"),
        ("07.5.2026",  "07/05/2026"),
        ("1.1.2020",   "01/01/2020"),
    ]
    for raw_date, expected_fmt in date_tests:
        parsed = pd.to_datetime(raw_date, format="mixed", dayfirst=True, errors="coerce")
        formatted = parsed.strftime("%d/%m/%Y")
        passed = formatted == expected_fmt
        status = "✓" if passed else "✗"
        if not passed:
            all_pass = False
        print(f"  {status}  {repr(raw_date):<15} → {formatted}")

    print("───────────────────────────────────────────────")
    print(f"   Kết quả: {'TẤT CẢ PASS ✓' if all_pass else 'CÓ LỖI ✗'}")
    return all_pass


if __name__ == "__main__":
    _run_unit_tests()
    df_clean = clean_bog_petrolimex()