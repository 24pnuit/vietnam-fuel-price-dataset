from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import undetected_chromedriver as uc
import pandas as pd
import re
import os
import shutil
from datetime import datetime

# CONFIG PATHS
_HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.getcwd()
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))

CRAWL_FILE = os.path.join(_ROOT, "data", "raw", "bog_pvoil.csv")
PARSED_FILE = os.path.join(_ROOT, "data", "interim", "parsed_bog_pvoil.csv")

def main():
    # READ CRAWL FILE
    crawl_df = pd.read_csv(CRAWL_FILE)
    unparsed = crawl_df[crawl_df["is_parsed"] == 0]
    print(f"[1] Đọc file crawl từ raw: {crawl_df.shape[0]} bài, cần parse: {unparsed.shape[0]} bài\n")

    date_str = datetime.today().strftime("%Y%m%d_%H%M")
    shutil.copy(CRAWL_FILE, CRAWL_FILE.replace(".csv", f"_before_update_{date_str}.csv"))
    print(f"[1] Đã backup crawl: {CRAWL_FILE.replace('.csv', f'_before_update_{date_str}.csv')}\n")

    # READ OLD PARSED FILE + BACKUP
    if os.path.exists(PARSED_FILE):
        parsed_df = pd.read_csv(PARSED_FILE)
        print(f"[2] Đọc file parsed cũ tại interim: {parsed_df.shape[0]} bài\n")
        
        shutil.copy(PARSED_FILE, PARSED_FILE.replace(".csv", f"_before_update_{date_str}.csv"))
        print(f"[2] Đã backup parsed: {PARSED_FILE.replace('.csv', f'_before_update_{date_str}.csv')}\n")
    else:
        parsed_df = pd.DataFrame()
        print("[2] Chưa có file parsed trong interim: tạo mới\n")

    # PARSE DATA
    driver = uc.Chrome(version_main=148)
    wait = WebDriverWait(driver, 20)

    new_parsed_rows = []

    for idx, row in unparsed.iterrows():
        try:
            print(f"[3] Đang parse: {row['title']}")

            driver.get(row["detail_url"])
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.full-content")))

            detail_text = driver.find_element(By.CSS_SELECTOR, "div.full-content").text
            detail_text = detail_text.split("PVOIL News")[0]

            uoc_ton = None

            # ===== DẠNG MỚI =====
            match = re.search(r"[-+]?\d[\d.,]*\s*tỷ\s*đồng", detail_text, re.IGNORECASE)
            if match:
                uoc_ton = match.group()

            # ===== DẠNG CŨ =====
            else:
                numbers = re.search(r':\s*([^:]*?VNĐ)(?!.*VNĐ)', detail_text, re.IGNORECASE | re.DOTALL)
                if numbers:
                    uoc_ton = numbers.group(1).strip()

            new_parsed_rows.append({
                "title":       row["title"],
                "report_date": row["report_date"],
                "detail_url":  row["detail_url"],
                "bog_pvoil":   uoc_ton,
            })

            crawl_df.loc[idx, "is_parsed"] = 1
            crawl_df.to_csv(CRAWL_FILE, index=False, encoding="utf-8-sig")

        except Exception as e:
            print(f"Lỗi: {row['title']} — {e}")
            continue

    driver.quit()

    print(f"\n[3] Parse được {len(new_parsed_rows)} bài mới\n")

    # MERGE PARSED DATA
    new_parsed_df = pd.DataFrame(new_parsed_rows)

    if not new_parsed_df.empty:
        parsed_df = pd.concat([new_parsed_df, parsed_df], ignore_index=True).drop_duplicates(subset=["detail_url"], keep="last")
        print(f"[4] Đã thêm {len(new_parsed_rows)} bài mới vào file parsed\n")
    else:
        print("[4] Không có bài mới để thêm\n")

    # SAVE TO INTERIM
    parsed_df.to_csv(PARSED_FILE, index=False, encoding="utf-8-sig")

    print(f"[5] Đã lưu thành công: {PARSED_FILE} ({parsed_df.shape[0]} bài tổng cộng)")

if __name__ == "__main__":
    main()