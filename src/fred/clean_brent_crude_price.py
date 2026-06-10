import os
import pandas as pd


# ── Cấu hình Đường dẫn ────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.getcwd()
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))

INPUT_PATH  = os.path.join(_ROOT, "data", "raw", "brent_crude_price.csv")
OUTPUT_PATH = os.path.join(_ROOT, "data", "interim", "cleaned_brent_crude_price.csv")
START_DATE  = "2018-05-01"                       

# Cột gốc trong file raw → tên chuẩn hóa
COL_DATE  = "observation_date"
COL_PRICE = "DCOILBRENTEU"

# Tạo sẵn thư mục lưu trữ nếu chưa tồn tại
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)


# ── Hàm validate giá ──────────────────────────────────────────────────────────
def _check_price_anomalies(df: pd.DataFrame, verbose: bool = True) -> None:
    non_null = df.dropna(subset=["brent_usd_per_barrel"]) 

    # Giá bằng 0 (giá âm đã được xử lý thành 0 trước đó)
    mask_zero = non_null["brent_usd_per_barrel"] == 0   
    if mask_zero.any():
        print(f"  [!] CẢNH BÁO: {mask_zero.sum()} dòng có giá = 0 USD/bbl (đã convert từ giá âm):")
        print(non_null[mask_zero][["date", "brent_usd_per_barrel"]].to_string())

    # Biến động ngày > 20%
    pct_change = non_null["brent_usd_per_barrel"].pct_change().abs()  
    mask_spike = pct_change > 0.20
    if mask_spike.any():
        print(f"  [!] CẢNH BÁO: {mask_spike.sum()} dòng có biến động ngày > 20%:")
        print(non_null[mask_spike][["date", "brent_usd_per_barrel"]].to_string())

    if verbose and not mask_zero.any() and not mask_spike.any():
        print("    OK — không phát hiện giá trị bất thường")


# ── Pipeline chính ─────────────────────────────────────────────────────────────
def clean_brent_crude(
    raw_path: str = INPUT_PATH,
    output_path: str = OUTPUT_PATH,
    start_date: str = START_DATE,
    verbose: bool = True,
) -> pd.DataFrame:

    # ── 1. Đọc file ───────────────────────────────────────────────────────────
    df = pd.read_csv(raw_path)
    if verbose:
        print(f"[1] Đọc file: {len(df)} dòng")

    # ── 2. Parse ngày & chuẩn hóa định dạng DD/MM/YYYY ───────────────────────
    df["date"] = pd.to_datetime(df[COL_DATE], format="%Y-%m-%d", errors="coerce")
    n_date_fail = df["date"].isna().sum()
    if n_date_fail > 0:
        print(f"[!] CẢNH BÁO: {n_date_fail} dòng parse ngày thất bại")
    elif verbose:
        print(f"[2] Parse ngày: OK — {df['date'].min().date()} → {df['date'].max().date()}")

    # ── 3. Lọc từ start_date ──────────────────────────────────────────────────
    df = df[df["date"] >= start_date].copy()
    if verbose:
        print(f"[3] Lọc từ {start_date}: còn {len(df)} dòng")

    # ── 4. Đổi tên cột giá & chuẩn hóa sang số ───────────────────────────────
    df = df.rename(columns={COL_PRICE: "brent_usd_per_barrel"})  
    df["brent_usd_per_barrel"] = pd.to_numeric(                 
        df["brent_usd_per_barrel"], errors="coerce"
    )
    if verbose:
        non_null_count = df["brent_usd_per_barrel"].notna().sum()
        print(
            f"[4] Chuẩn hóa kiểu dữ liệu: OK — {non_null_count} giá trị số, "
            f"range [{df['brent_usd_per_barrel'].min():.2f}, {df['brent_usd_per_barrel'].max():.2f}] USD/bbl"
        )

    # ── 5. Giá âm → 0 ────────────────────────────────────────────────────────
    mask_neg = df["brent_usd_per_barrel"] < 0
    n_neg = mask_neg.sum()
    if n_neg > 0:
        df.loc[mask_neg, "brent_usd_per_barrel"] = 0
        print(f"[5] Giá âm → 0: đã xử lý {n_neg} dòng")
    elif verbose:
        print(f"[5] Giá âm → 0: không có dòng nào")

    # ── 6. Kiểm tra NaN ───────────────────────────────────────────────────────
    n_nan = df["brent_usd_per_barrel"].isna().sum()
    if verbose:
        print(f"[6] NaN: {n_nan} dòng — GIỮ NGUYÊN (cuối tuần & ngày lễ)")

    # ── 7. Kiểm tra giá trị bất thường ───────────────────────────────────────
    if verbose:
        print("[7] Kiểm tra anomaly...")
    _check_price_anomalies(df, verbose=verbose)

    # ── 8. Kiểm tra trùng ngày ────────────────────────────────────────────────
    dup = df["date"].duplicated()                          
    if dup.sum() > 0:
        print(f"[!] CẢNH BÁO: Phát hiện {dup.sum()} dòng trùng ngày → giữ dòng đầu tiên")
        df = df[~dup].copy()
        print(f"    → Còn {len(df)} dòng")
    elif verbose:
        print(f"[8] Kiểm tra trùng ngày: OK — không có trùng")

    # ── 9. Chọn cột output, sắp xếp & format ngày DD/MM/YYYY ─────────────────
    result = (
        df[["date", "brent_usd_per_barrel"]]             
        .sort_values("date")
        .reset_index(drop=True)
    )
    result["date"] = result["date"].dt.strftime("%d/%m/%Y")

    # ── 10. Lưu file ──────────────────────────────────────────────────────────
    result.to_csv(output_path, index=False)
    if verbose:
        print(f"[9] Lưu thành công: {output_path}")
        print(f"\n── Thống kê cuối ──────────────────────────────")
        print(f"   Số dòng          : {len(result)}")
        print(f"   Date range       : {result['date'].iloc[0]} → {result['date'].iloc[-1]}")
        non_null = result["brent_usd_per_barrel"].dropna()
        print(f"   Brent min        : {non_null.min():.2f} USD/bbl")
        print(f"   Brent max        : {non_null.max():.2f} USD/bbl")
        print(f"   Brent mean       : {non_null.mean():.2f} USD/bbl")
        print(f"   NaN (giữ nguyên) : {result['brent_usd_per_barrel'].isna().sum()} dòng")
        print(f"───────────────────────────────────────────────")

    return result


# ── Unit tests ─────────────────────────────────────────────────────────────────
def _run_unit_tests():
    import numpy as np

    print("── Unit tests clean_brent_crude ────────────────")
    all_pass = True

    # Test 1: parse ngày ISO
    dates = pd.to_datetime(
        pd.Series(["2018-05-01", "2020-01-01", "2022-12-31"]),
        format="%Y-%m-%d",
        errors="coerce",
    )
    t1 = dates.isna().sum() == 0
    _print_test("Parse ngày ISO 8601", t1)
    all_pass = all_pass and t1

    # Test 2: lọc start_date 01/05/2018                  
    df_mock = pd.DataFrame({
        "date": pd.to_datetime(["2018-04-30", "2018-05-01", "2018-05-02"]),
        "brent_usd_per_barrel": [70.0, 71.0, 72.0],
    })
    df_filtered = df_mock[df_mock["date"] >= START_DATE]
    t2 = len(df_filtered) == 2 and df_filtered["date"].min() == pd.Timestamp("2018-05-01")
    _print_test("Lọc từ START_DATE 01/05/2018", t2)
    all_pass = all_pass and t2

    # Test 3: NaN được giữ nguyên (không drop)
    df_nan = pd.DataFrame({
        "date": pd.to_datetime(["2022-01-01", "2022-01-02", "2022-01-03"]),
        "brent_usd_per_barrel": [80.0, np.nan, 81.0],
    })
    t3 = df_nan["brent_usd_per_barrel"].isna().sum() == 1
    _print_test("Giữ nguyên NaN (không drop)", t3)
    all_pass = all_pass and t3

    # Test 4: giá âm → 0                                 
    df_neg = pd.DataFrame({
        "date": pd.to_datetime(["2020-04-20", "2020-04-21"]),
        "brent_usd_per_barrel": [-37.63, 15.0],
    })
    df_neg.loc[df_neg["brent_usd_per_barrel"] < 0, "brent_usd_per_barrel"] = 0
    t4 = df_neg["brent_usd_per_barrel"].iloc[0] == 0
    _print_test("Giá âm → 0", t4)
    all_pass = all_pass and t4

    # Test 5: phát hiện trùng ngày & giữ dòng đầu
    df_dup = pd.DataFrame({
        "date": pd.to_datetime(["2022-01-01", "2022-01-01", "2022-01-02"]),
        "brent_usd_per_barrel": [80.0, 81.0, 82.0],
    })
    dup_mask = df_dup["date"].duplicated()                
    df_dedup = df_dup[~dup_mask]
    t5 = len(df_dedup) == 2 and df_dedup["brent_usd_per_barrel"].iloc[0] == 80.0
    _print_test("Trùng ngày → giữ dòng đầu", t5)
    all_pass = all_pass and t5

    # Test 6: format ngày output DD/MM/YYYY              
    df_fmt = pd.DataFrame({
        "date": pd.to_datetime(["2018-05-01"]),
        "brent_usd_per_barrel": [74.85],
    })
    df_fmt["date"] = df_fmt["date"].dt.strftime("%d/%m/%Y")
    t6 = df_fmt["date"].iloc[0] == "01/05/2018"
    _print_test("Format ngày output DD/MM/YYYY", t6)
    all_pass = all_pass and t6

    # Test 7: sắp xếp tăng dần theo ngày
    df_desc = pd.DataFrame({
        "date": pd.to_datetime(["2022-01-03", "2022-01-01", "2022-01-02"]),
        "brent_usd_per_barrel": [82.0, 80.0, 81.0],
    }).sort_values("date").reset_index(drop=True)
    t7 = list(df_desc["brent_usd_per_barrel"]) == [80.0, 81.0, 82.0]
    _print_test("Sắp xếp tăng dần theo ngày", t7)
    all_pass = all_pass and t7

    print("───────────────────────────────────────────────")
    print(f"   Kết quả: {'TẤT CẢ PASS ✓' if all_pass else 'CÓ LỖI ✗'}")
    return all_pass


def _print_test(name: str, passed: bool):
    status = "✓" if passed else "✗"
    print(f"  {status}  {name}")


# ── Entrypoint ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("Phase 1 — Clean Brent Crude Price")
    print("=" * 50)

    print("\n[Unit Tests]")
    _run_unit_tests()

    print("\n[Pipeline]")
    df_clean = clean_brent_crude()