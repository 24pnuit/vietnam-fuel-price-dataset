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
RAW_DIR = os.path.join(_ROOT, "data", "raw")
os.makedirs(RAW_DIR, exist_ok=True)

CRAWL_FILE = os.path.join(RAW_DIR, "bog_petrolimex.csv")
BASE_URL = "https://www.petrolimex.com.vn/ndi/minh-bach-xang-dau.html"
KEYWORDS = ["ước", "tồn", "quỹ"]
CRAWL_DATE = datetime.today().strftime("%Y-%m-%d")

def main():
    # READ OLD DATA + BACKUP
    if os.path.exists(CRAWL_FILE):
        old_df = pd.read_csv(CRAWL_FILE)
        old_urls = set(old_df["detail_url"].dropna().tolist())
        print(f"[1] Đã đọc file cũ tại raw: {old_df.shape[0]} bài\n")

        date_str = datetime.today().strftime("%Y%m%d_%H%M")
        backup_path = CRAWL_FILE.replace(".csv", f"_before_update_{date_str}.csv")
        shutil.copy(CRAWL_FILE, backup_path)
        print(f"[2] Đã backup vào raw: {backup_path}\n")
    else:
        old_df = pd.DataFrame()
        old_urls = set()
        print("[1] Chưa có file cũ trong raw: tạo mới\n")

    # SELENIUM INITIALIZATION
    driver = webdriver.Chrome()
    wait = WebDriverWait(driver, 10)
    driver.get(BASE_URL)

    new_urls = []
    page = 0
    stop_crawl = False

    while not stop_crawl:
        page += 1
        print(f"[3] Đang xử lý page {page}")

        wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.post-default")))
        posts = driver.find_elements(By.CSS_SELECTOR, "div.post-default")

        for post in posts:
            try:
                title_element = post.find_element(By.CSS_SELECTOR, "h3.post-default__title a")
                title = title_element.text.strip()
                detail_url = title_element.get_attribute("href")

                if detail_url in old_urls:
                    print(f"→ Đã gặp dữ liệu cũ ({detail_url}): dừng crawl")
                    stop_crawl = True
                    break
                    
                if all(k in title.lower() for k in KEYWORDS):
                    try:
                        meta_div = post.find_element(By.CSS_SELECTOR, "div.post-default__meta")
                        meta_text = meta_div.text.strip()
                        match_date = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", meta_text)
                        post_date = (match_date.group(1) if match_date else None)
                    except:
                        post_date = None

                    match_report_date = re.search(r"\d{1,2}[./]\d{1,2}[./]\d{4}", title)
                    report_date = match_report_date.group() if match_report_date else None
                    
                    new_urls.append({
                        "crawl_date":  CRAWL_DATE,
                        "detail_url":  detail_url,
                        "title":       title,
                        "report_date": report_date,
                        "post_date":   post_date,
                        "is_parsed":   0
                    })

            except Exception as e:
                print(f"Lỗi bài viết tại page {page}: {e}")
                continue

        if stop_crawl:
            break

        # PAGINATION
        try:
            old_first_post = posts[0]
            next_button = driver.find_element(By.CSS_SELECTOR, "a.btn-next")
            next_button.click()
            
            wait.until(EC.staleness_of(old_first_post))
            wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.post-default")))

        except Exception as e:
            print(f"→ Không còn trang tiếp hoặc lỗi phân trang: dừng - {e}")
            break

    driver.quit()

    print(f"\n[3] Tìm được {len(new_urls)} bài mới\n")

    # MERGE DATA
    new_df = pd.DataFrame(new_urls)

    if not new_df.empty:
        df = pd.concat([new_df, old_df], ignore_index=True).drop_duplicates(subset=["detail_url"], keep="last")
        print(f"[4] Đã thêm {len(new_urls)} bài mới vào tập dữ liệu\n")
    else:
        df = old_df.copy()
        print("[4] Không có bài mới\n")

    # SAVE TO RAW
    df.to_csv(CRAWL_FILE, index=False, encoding="utf-8-sig")

    print(f"[5] Đã lưu thành công: {CRAWL_FILE} ({df.shape[0]} bài tổng cộng)")
    
if __name__ == "__main__":
    main()