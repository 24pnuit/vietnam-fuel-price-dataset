from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
import os

# CONFIG PATHS
_HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.getcwd()
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
RAW_DIR = os.path.join(_ROOT, "data", "raw")
os.makedirs(RAW_DIR, exist_ok=True)

OUTPUT_FILE = os.path.join(RAW_DIR, "van_ban_dieu_hanh.csv")

BASE_URL = "https://moit.gov.vn/van-ban-phap-luat/van-ban-dieu-hanh"
KEYWORDS = ["điều hành", "xăng dầu"]

def main():
    # READ OLD DATA
    if os.path.exists(OUTPUT_FILE):
        old_df = pd.read_csv(OUTPUT_FILE)
        old_urls = set(old_df["detail_url"].dropna().tolist())
        print(f"[1] Đã đọc file cũ tại raw: {old_df.shape[0]} bài\n")
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
        print(f"[2] Đang xử lý page {page}")

        wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "table tbody tr")))
        rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")

        for row in rows:
            try:
                title_ele = row.find_element(By.CSS_SELECTOR, "td.tg-yw4l a")
                title = title_ele.text.strip()
                detail_url = title_ele.get_attribute("href")
                
                if detail_url in old_urls:
                    print(f"→ Đã gặp dữ liệu cũ ({detail_url}): dừng crawl")
                    stop_crawl = True
                    break

                cols = row.find_elements(By.TAG_NAME, "td")
                doc_number = cols[2].text.strip() if len(cols) > 2 else None
                operation_date = cols[3].text.strip() if len(cols) > 3 else None

                if all(k in title.lower() for k in KEYWORDS):
                    new_urls.append({
                        "title":          title,
                        "doc_number":     doc_number,
                        "operation_date": operation_date,
                        "detail_url":     detail_url,
                    })

            except Exception as e:
                print(f"Lỗi bài viết tại page {page}: {e}")
                continue

        if stop_crawl:
            break

        # PAGINATION
        try:
            old_first_row = rows[0]
            next_button = driver.find_element(By.CSS_SELECTOR, "div.default-pagination a.next")
            next_button.click()
            
            wait.until(EC.staleness_of(old_first_row))
            wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "table tbody tr")))
            
        except Exception as e:
            print(f"→ Không còn trang tiếp hoặc lỗi phân trang: dừng - {e}")
            break

    driver.quit()

    print(f"[2] Tìm được {len(new_urls)} bài mới\n")

    # MERGE DATA
    new_df = pd.DataFrame(new_urls)

    if not new_df.empty:
        df = pd.concat([new_df, old_df], ignore_index=True).drop_duplicates(subset=["detail_url"], keep="last")
        print(f"[3] Đã thêm {len(new_urls)} bài mới vào tập dữ liệu\n")
    else:
        df = old_df.copy()
        print("[3] Không có bài mới\n")

    # SAVE TO RAW
    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    print(f"[4] Đã lưu thành công: {OUTPUT_FILE} ({df.shape[0]} bài tổng cộng)")

if __name__ == "__main__":
    main()