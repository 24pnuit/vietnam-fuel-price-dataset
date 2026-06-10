from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
import re
import os
import shutil
from datetime import datetime

# CONFIG PATHS
_HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.getcwd()
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))

CRAWL_FILE = os.path.join(_ROOT, "data", "raw", "bog_petrolimex.csv")
PARSED_FILE = os.path.join(_ROOT, "data", "interim", "parsed_bog_petrolimex.csv")

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
    driver = webdriver.Chrome()
    wait = WebDriverWait(driver, 10)

    new_parsed_rows = []

    for idx, row in unparsed.iterrows():
        try:
            print(f"[4] Đang parse: {row['title']}")
            
            driver.get(row["detail_url"])
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.entry-detail")))

            detail_div = driver.find_element(By.CSS_SELECTOR, "div.entry-detail")
            detail_text = detail_div.text

            part_1 = detail_text.split("Đây là số ước tính")[0]
            part_2 = part_1.split(":")[-1].strip()
            part_final = re.search(r".*?tỷ\s*đồng", part_2, re.IGNORECASE)
            uoc_ton = part_final.group() if part_final else None

            new_parsed_rows.append({
                "title":          row["title"],
                "report_date":    row["report_date"],
                "detail_url":     row["detail_url"],
                "bog_petrolimex": uoc_ton,
            })

            crawl_df.loc[idx, "is_parsed"] = 1
            crawl_df.to_csv(CRAWL_FILE, index=False, encoding="utf-8-sig")

        except Exception as e:
            print(f"Lỗi: {row['title']} — {e}")
            continue

    driver.quit()

    print(f"\n[4] Parse được {len(new_parsed_rows)} bài mới\n")

    # MERGE PARSED DATA
    new_parsed_df = pd.DataFrame(new_parsed_rows)

    if not new_parsed_df.empty:
        parsed_df = pd.concat([new_parsed_df, parsed_df], ignore_index=True).drop_duplicates(subset=["detail_url"], keep="last")
        print(f"[5] Đã thêm {len(new_parsed_rows)} bài mới vào file parsed\n")
    else:
        print("[5] Không có bài mới để thêm\n")

    # SAVE TO INTERIM
    parsed_df.to_csv(PARSED_FILE, index=False, encoding="utf-8-sig")

    print(f"[6] Đã lưu thành công: {PARSED_FILE} ({parsed_df.shape[0]} bài tổng cộng)")

if __name__ == "__main__":
    main()