import re
import time
import hashlib
from urllib.parse import urlencode, urljoin

import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from config.settings import (
    BASE_SITE,
    SEARCH_BASE_URL,
    DOCUMENT_REGISTRY_FILE,
    RAW_DIR,
)
from src.utils import ensure_directories, append_log, today_str, safe_read_csv


REGISTRY_COLUMNS = [
    "doc_id",
    "title",
    "issue_date",
    "updated_date",
    "detail_url",
    "page_found",
    "source_keyword",
    "crawl_date",
    "crawl_status",
    "parse_status",
    "data_quality_flag",
    "status",
]

TITLE_PAT = re.compile(
    r"công văn\s+.+?\bBCT-TTTN\b.+?(thông báo điều hành giá bán xăng dầu|điều hành kinh doanh xăng dầu)",
    re.IGNORECASE
)

ISSUE_PAT = re.compile(r"Ban hành:\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
UPDATED_PAT = re.compile(r"Cập nhật:\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE)

BLOCK_SIGNALS = [
    "xác minh bạn là người",
    "xác minh bạn không phải là bot",
    "thực hiện xác minh bảo mật",
    "cloudflare",
    "ray id",
    "chờ một chút",
    "nhập mã",
    "mã xác nhận",
]


def build_search_url(page: int = 1) -> str:
    params = {
        "keyword": "điều hành",
        "area": 0,
        "type": 3,
        "status": 0,
        "lan": 1,
        "org": 0,
        "signer": 0,
        "match": "True",
        "sort": 1,
        "bdate": "20/04/1946",
        "edate": "21/04/2026",
        "page": page,
    }
    return f"{SEARCH_BASE_URL}?{urlencode(params)}"


def build_driver():
    options = Options()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
    driver = webdriver.Chrome(options=options)
    return driver


def make_doc_id(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:16]


def save_search_page_html(page: int, html: str):
    search_pages_dir = RAW_DIR / "search_pages"
    search_pages_dir.mkdir(parents=True, exist_ok=True)

    path = search_pages_dir / f"update_page_{page:03d}.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    append_log(f"SAVED_SEARCH_HTML={path}")


def detect_page_status(page_title: str, body_text: str, html: str) -> str:
    merged = f"{page_title} {body_text} {html[:2000]}".lower()

    for sig in BLOCK_SIGNALS:
        if sig in merged:
            return "blocked"

    if "kết quả" in merged and "công văn" in merged:
        return "ok"

    return "unknown"


def parse_page(html: str, page: int):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()

        if "/cong-van/" not in href:
            continue
        if not title:
            continue
        if "BCT-TTTN" not in title.upper():
            continue
        if "BTC" in title.upper():
            continue
        if not TITLE_PAT.search(title):
            continue

        abs_url = urljoin(BASE_SITE, href)
        if abs_url in seen:
            continue
        seen.add(abs_url)

        parent_text = ""
        current = a
        for _ in range(6):
            current = getattr(current, "parent", None)
            if current is None:
                break
            txt = current.get_text(" ", strip=True)
            if len(txt) > len(parent_text):
                parent_text = txt

        issue_date = None
        updated_date = None

        m1 = ISSUE_PAT.search(parent_text)
        if m1:
            issue_date = m1.group(1)

        m2 = UPDATED_PAT.search(parent_text)
        if m2:
            updated_date = m2.group(1)

        rows.append({
            "doc_id": make_doc_id(abs_url),
            "title": title,
            "issue_date": issue_date,
            "updated_date": updated_date,
            "detail_url": abs_url,
            "page_found": page,
            "source_keyword": "điều hành",
            "crawl_date": today_str(),
            "crawl_status": "not_fetched",
            "parse_status": "not_parsed",
            "data_quality_flag": None,
            "status": "discovered",
        })

    return rows


def normalize_registry(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=REGISTRY_COLUMNS)

    df = df.copy()

    for col in REGISTRY_COLUMNS:
        if col not in df.columns:
            df[col] = None

    df["title"] = df["title"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()

    df = df[
        df["title"].str.contains(r"\bBCT-TTTN\b", case=False, na=False)
        & ~df["title"].str.contains(r"\bBTC\b", case=False, na=False)
    ].copy()

    df = df.drop_duplicates(subset=["detail_url"], keep="last").reset_index(drop=True)
    return df[REGISTRY_COLUMNS]


def merge_registry(old_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    if old_df.empty:
        return new_df.copy()

    # giữ trạng thái cũ nếu URL đã tồn tại
    combined = pd.concat([old_df, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["detail_url"], keep="first").reset_index(drop=True)

    return combined


def discover(max_pages=3):
    ensure_directories()
    append_log("DISCOVERY: start (update-only mode)")

    old_df = safe_read_csv(DOCUMENT_REGISTRY_FILE)
    if old_df.empty:
        old_df = pd.DataFrame(columns=REGISTRY_COLUMNS)
    old_df = normalize_registry(old_df)

    driver = build_driver()
    all_rows = []
    page_audit = []

    for page in range(1, max_pages + 1):
        url = build_search_url(page)
        append_log(f"DISCOVERY: page={page}")
        append_log(f"DISCOVERY: url={url}")

        driver.get(url)
        time.sleep(4)

        page_title = driver.title
        body_text = driver.find_element("tag name", "body").text
        html = driver.page_source

        append_log(f"PAGE_TITLE={page_title}")
        append_log(f"BODY_PREVIEW={body_text[:400].replace(chr(10), ' | ')}")

        save_search_page_html(page, html)

        page_status = detect_page_status(page_title, body_text, html)
        append_log(f"PAGE_STATUS={page_status}")

        if page_status == "blocked":
            append_log("DISCOVERY WARNING: blocked/captcha detected. Please solve it in Chrome, then rerun.")
            page_audit.append({
                "page": page,
                "status": "blocked",
                "docs_found": 0,
            })
            break

        rows = parse_page(html, page=page)
        docs_found = len(rows)

        append_log(f"DISCOVERY: found {docs_found} docs on page {page}")

        page_audit.append({
            "page": page,
            "status": page_status,
            "docs_found": docs_found,
        })

        all_rows.extend(rows)

    driver.quit()

    new_df = pd.DataFrame(all_rows, columns=REGISTRY_COLUMNS)
    new_df = normalize_registry(new_df)

    old_n = len(old_df)

    # chỉ giữ những URL mới chưa có trong baseline
    if not old_df.empty and not new_df.empty:
        new_df = new_df[~new_df["detail_url"].isin(old_df["detail_url"])].copy()

    added_n = len(new_df)

    merged_df = merge_registry(old_df, new_df)
    merged_df = normalize_registry(merged_df)
    merged_df.to_csv(DOCUMENT_REGISTRY_FILE, index=False, encoding="utf-8-sig")

    audit_path = RAW_DIR / "search_pages" / "page_audit.csv"
    pd.DataFrame(page_audit).to_csv(audit_path, index=False, encoding="utf-8-sig")
    append_log(f"PAGE_AUDIT_SAVED={audit_path}")

    append_log(f"DISCOVERY DONE: old={old_n}, added={added_n}, merged={len(merged_df)}")


if __name__ == "__main__":
    discover(max_pages=3)