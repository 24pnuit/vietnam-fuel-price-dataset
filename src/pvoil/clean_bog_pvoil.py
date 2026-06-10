import re
import os
import pandas as pd

# CONFIG PATHS
_HERE        = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.getcwd()
_ROOT        = os.path.abspath(os.path.join(_HERE, "..", ".."))

RAW_PATH    = os.path.join(_ROOT, "data", "interim", "parsed_bog_pvoil.csv")
OUTPUT_PATH = os.path.join(_ROOT, "data", "interim", "cleaned_bog_pvoil.csv")
START_DATE  = "2018-05-01"                     

# Tạo sẵn folder interim/clean nếu chưa có
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

# Giá trị nghi vấn cần cảnh báo (raw_string: ghi chú)
KNOWN_ANOMALIES = {
    "-7113,40 tỷ đồng": (
        "Ngày 21/11/2022 — khả năng typo của '-711,34 tỷ đồng' "
        "(láng giềng: -679,48 và -723,702). "
        "Giữ nguyên giá trị parse được, kiểm tra lại bản gốc trên pvoil.com.vn."
    ),
}


# ── Hàm parse số ──────────────────────────────────────────────────────────────
def _parse_number_ty_dong(num_str: str) -> float:
    s = num_str.strip()

    if "." in s and "," in s:
        # Dạng "1.611,45": . = ngàn, , = thập phân
        s = s.replace(".", "").replace(",", ".")

    elif "," in s:
        # Chỉ có dấu phẩy → luôn là thập phân
        # "872,58" → 872.58 | "723,702" → 723.702 | "7113,40" → 7113.40
        s = s.replace(",", ".")

    elif "." in s:
        parts = s.split(".")
        if len(parts) == 2 and len(parts[1]) == 3:
            # "1.000" → đúng 3 chữ số sau . → ngàn phân cách → 1000
            s = parts[0] + parts[1]
        # "668.6" (1-2 chữ số) → giữ nguyên

    return float(s)


def _parse_vnd_to_ty(num_str: str) -> float:
    s = num_str.strip()

    if s.count(".") > 1:
        # "64.359.556.266" → xóa tất cả . → "64359556266"
        s = s.replace(".", "")
    elif s.count(",") > 1:
        # "37,576,277,356" → xóa tất cả , → "37576277356"
        s = s.replace(",", "")

    return float(s) / 1e9  # VNĐ → tỷ đồng


# ── Hàm parse giá trị BOG PVOil ───────────────────────────────────────────────
def parse_pvoil_value(raw: str) -> float | None:
    if not isinstance(raw, str):
        return None

    s = raw.strip()

    # ── Cảnh báo giá trị nghi vấn ─────────────────────────────────────────────
    for anomaly, note in KNOWN_ANOMALIES.items():
        if anomaly in s:
            print(f"  [!] CẢNH BÁO giá trị nghi vấn: {repr(s)}")
            print(f"      {note}")

    # ── Xác định dấu ──────────────────────────────────────────────────────────
    sign = -1 if s.startswith("-") else 1

    # ── Nhóm D: đơn vị VNĐ ───────────────────────────────────────────────────
    if re.search(r"VNĐ|VND", s, re.IGNORECASE):
        m = re.search(r"-?([\d.,]+)", s)
        if m:
            return sign * _parse_vnd_to_ty(m.group(1))
        return None

    # ── Nhóm A, B, C: đơn vị tỷ đồng ────────────────────────────────────────
    m = re.search(r"-?([\d.,]+)\s*tỷ", s, re.IGNORECASE)
    if m:
        return sign * _parse_number_ty_dong(m.group(1))

    return None


# ── Pipeline chính ─────────────────────────────────────────────────────────────
def clean_bog_pvoil(
    raw_path: str = RAW_PATH,
    output_path: str = OUTPUT_PATH,
    start_date: str = START_DATE,
    verbose: bool = True,
) -> pd.DataFrame:

    # ── 1. Đọc file từ interim/parsed ─────────────────────────────────────────
    df = pd.read_csv(raw_path)
    if verbose:
        print(f"[1] Đọc file từ interim/parsed: {len(df)} dòng")

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
    if verbose:
        print("[4] Parse giá trị BOG...")
    df["pvoil_bog_ty_dong"] = df["bog_pvoil"].apply(parse_pvoil_value)
    df["pvoil_bog_ty_dong"] = pd.to_numeric(
        df["pvoil_bog_ty_dong"], errors="coerce"
    )

    n_parse_fail = df["pvoil_bog_ty_dong"].isna().sum()
    if n_parse_fail > 0:
        print(f"[!] CẢNH BÁO: {n_parse_fail} dòng parse BOG thất bại")
        print(df[df["pvoil_bog_ty_dong"].isna()][["date", "bog_pvoil"]].to_string())
    elif verbose:
        non_null = df["pvoil_bog_ty_dong"].dropna()
        print(
            f"    OK — {len(non_null)} giá trị số, "
            f"range [{non_null.min():.2f}, {non_null.max():.2f}] tỷ đồng"
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
        df[["date", "pvoil_bog_ty_dong"]]       
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
        non_null = result["pvoil_bog_ty_dong"].dropna()
        print(f"   BOG min          : {non_null.min():.2f} tỷ đồng")
        print(f"   BOG max          : {non_null.max():.2f} tỷ đồng")
        print(f"   BOG mean         : {non_null.mean():.2f} tỷ đồng")
        print(f"   NaN              : {result['pvoil_bog_ty_dong'].isna().sum()} dòng")
        print(f"───────────────────────────────────────────────")

    return result


# ── Unit tests ─────────────────────────────────────────────────────────────────
def _run_unit_tests():
    print("── Unit tests parse_pvoil_value ────────────────")
    tests = [
        ("-1.611,45 tỷ đồng",       -1611.45),
        ("-1.000,77 tỷ đồng",       -1000.77),
        ("-872,58 tỷ đồng",          -872.58),
        ("-723,702 tỷ đồng",         -723.702),
        ("-22,08 tỷ đồng",            -22.08),
        ("13,87 tỷ đồng",              13.87),
        ("40,8 tỷ đồng",               40.8),
        ("-668.6 tỷ đồng",            -668.6),
        ("-304.4 tỷ đồng",            -304.4),
        ("-49.4 tỷ đồng",              -49.4),
        ("64.359.556.266 VNĐ",         64.359556266),
        ("-62.416.530.114 VNĐ",       -62.41653011),
        ("194.058.207.992 VNĐ",       194.058207992),
        ("37,576,277,356 VNĐ",         37.576277356),
    ]

    all_pass = True
    for raw, expected in tests:
        result = parse_pvoil_value(raw)
        passed = result is not None and abs(result - expected) < 0.001
        status = "✓" if passed else "✗"
        if not passed:
            all_pass = False
        print(f"  {status}  {repr(raw):<40} → {result if result is not None else None}")

    print("\n── Unit tests format ngày ──────────────────────")
    date_tests = [
        ("28/5/2026",   "28/05/2026"),
        ("7/5/2026",    "07/05/2026"),
        ("29/04/2026",  "29/04/2026"),
        ("1/1/2018",    "01/01/2018"),
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


# ── Entrypoint ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _run_unit_tests()
    df_clean = clean_bog_pvoil()