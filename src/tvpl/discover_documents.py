# Bước 1 — chạy đầu tiên
# Dùng Selenium gắn vào Chrome đang mở (debuggerAddress) để vượt Cloudflare.
# Kết quả lưu vào: data/raw/document_registry.csv

import re
import time
import random
import hashlib
from urllib.parse import urlencode, urljoin

import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from settings import (
    BASE_SITE,
    SEARCH_BASE_URL,
    DOCUMENT_REGISTRY_FILE,
    RAW_DIR,
)
from utils import ensure_directories, append_log, today_str, safe_read_csv


# ── Schema ────────────────────────────────────────────────────────────────────
REGISTRY_COLUMNS = [
    "doc_id", "title", "issue_date", "updated_date", "detail_url",
    "page_found", "source_keyword", "crawl_date",
    "crawl_status", "parse_status", "data_quality_flag", "status",
]

# ── Regex ─────────────────────────────────────────────────────────────────────
TITLE_PAT = re.compile(
    r"công văn\s+.+?\bBCT-TTTN\b.+?(thông báo điều hành giá bán xăng dầu|điều hành kinh doanh xăng dầu)",
    re.IGNORECASE
)

ISSUE_PAT   = re.compile(r"Ban hành:\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
UPDATED_PAT = re.compile(r"Cập nhật:\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE)

BLOCK_SIGNALS = [
    "xác minh bạn là người", "xác minh bạn không phải là bot",
    "thực hiện xác minh bảo mật", "cloudflare", "ray id",
    "chờ một chút", "nhập mã", "mã xác nhận",
]


# ── Helpers ───────────────────────────────────────────────────────────────────
def build_search_url(page: int = 1) -> str:
    params = {
        "keyword": "điều hành", "area": 0, "type": 3, "status": 0,
        "lan": 1, "org": 0, "signer": 0, "match": "True",
        "sort": 1, "bdate": "20/04/1946", "edate": "21/04/2026", "page": page,
    }
    return f"{SEARCH_BASE_URL}?{urlencode(params)}"


def build_driver() -> webdriver.Chrome:
    options = Options()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
    return webdriver.Chrome(options=options)


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


def parse_page(html: str, page: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows, seen = [], set()

    for a in soup.find_all("a", href=True):
        href  = (a.get("href") or "").strip()
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()

        if "/cong-van/" not in href:
            continue
        if not title or "BCT-TTTN" not in title.upper():
            continue
        if "BTC" in title.upper():
            continue
        if not TITLE_PAT.search(title):
            continue

        abs_url = urljoin(BASE_SITE, href)
        if abs_url in seen:
            continue
        seen.add(abs_url)

        # Lấy text từ phần tử cha gần nhất có đủ thông tin
        parent_text, current = "", a
        for _ in range(6):
            current = getattr(current, "parent", None)
            if current is None:
                break
            txt = current.get_text(" ", strip=True)
            if len(txt) > len(parent_text):
                parent_text = txt

        m1 = ISSUE_PAT.search(parent_text)
        m2 = UPDATED_PAT.search(parent_text)

        rows.append({
            "doc_id":           make_doc_id(abs_url),
            "title":            title,
            "issue_date":       m1.group(1) if m1 else None,
            "updated_date":     m2.group(1) if m2 else None,
            "detail_url":       abs_url,
            "page_found":       page,
            "source_keyword":   "điều hành",
            "crawl_date":       today_str(),
            "crawl_status":     "not_fetched",
            "parse_status":     "not_parsed",
            "data_quality_flag": None,
            "status":           "discovered",
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
    """Ghép registry, giữ nguyên crawl_status cũ cho URL đã tồn tại."""
    if old_df.empty:
        return new_df.copy()
    combined = pd.concat([old_df, new_df], ignore_index=True)
    return combined.drop_duplicates(subset=["detail_url"], keep="first").reset_index(drop=True)


# ── Main ──────────────────────────────────────────────────────────────────────
def discover(max_pages: int = None):
    ensure_directories()
    append_log("DISCOVERY: start")

    old_df = safe_read_csv(DOCUMENT_REGISTRY_FILE)
    is_first_run = old_df.empty

    if max_pages is None:
        max_pages = 999 if is_first_run else 3

    append_log(f"DISCOVERY: {'lần đầu - crawl toàn bộ' if is_first_run else 'cập nhật - tối đa 3 trang'}")

    old_df = normalize_registry(old_df) if not old_df.empty else pd.DataFrame(columns=REGISTRY_COLUMNS)

    # Set URL đã biết — dùng để lọc duplicate trong loop
    existing_urls: set[str] = set(old_df["detail_url"].dropna().tolist())
    append_log(f"DISCOVERY: existing URLs = {len(existing_urls)}")

    driver = build_driver()
    new_rows: list[dict] = []
    page_audit: list[dict] = []

    for page in range(1, max_pages + 1):
        url = build_search_url(page)
        append_log(f"DISCOVERY: page={page} | {url}")
        
        driver.get(url)
        time.sleep(random.uniform(3.5, 8.0))

        page_title = driver.title
        body_text  = driver.find_element("tag name", "body").text
        html       = driver.page_source

        append_log(f"PAGE_TITLE={page_title}")
        append_log(f"BODY_PREVIEW={body_text[:300].replace(chr(10), ' | ')}")
        save_search_page_html(page, html)

        page_status = detect_page_status(page_title, body_text, html)
        append_log(f"PAGE_STATUS={page_status}")

        if page_status == "blocked":
            append_log("DISCOVERY: gặp captcha — đang chờ bạn giải trong Chrome...")
            solved = False
            for wait in range(24):          # chờ tối đa 24 × 5s = 120 giây
                time.sleep(5)
                html        = driver.page_source
                body_text   = driver.find_element("tag name", "body").text
                page_title  = driver.title
                page_status = detect_page_status(page_title, body_text, html)
                append_log(f"CAPTCHA WAIT {(wait + 1) * 5}s — status={page_status}")
                if page_status != "blocked":
                    append_log("DISCOVERY: captcha đã giải, tiếp tục...")
                    solved = True
                    break
            if not solved:
                append_log("DISCOVERY: chờ 2 phút vẫn còn blocked → dừng hẳn.")
                page_audit.append({"page": page, "status": "blocked", "docs_found": 0})
                break

        rows     = parse_page(html, page=page)
        new_only = [r for r in rows if r["detail_url"] not in existing_urls]
        skipped  = len(rows) - len(new_only)

        append_log(f"DISCOVERY: page {page} → {len(rows)} found, {skipped} đã có, {len(new_only)} mới")
        page_audit.append({"page": page, "status": page_status, "docs_found": len(new_only)})

        new_rows.extend(new_only)
        existing_urls.update(r["detail_url"] for r in new_only)

        # Dừng sớm nếu cả trang đều là URL cũ → đã crawl hết phần mới
        if rows and not new_only:
            append_log(f"DISCOVERY: page {page} toàn URL cũ → dừng sớm")
            break

    driver.quit()

    if not new_rows:
        append_log("DISCOVERY DONE: không có doc mới")
        # Vẫn lưu audit
        audit_path = RAW_DIR / "search_pages" / "page_audit.csv"
        pd.DataFrame(page_audit).to_csv(audit_path, index=False, encoding="utf-8-sig")
        return

    new_df     = normalize_registry(pd.DataFrame(new_rows, columns=REGISTRY_COLUMNS))
    merged_df  = normalize_registry(merge_registry(old_df, new_df))
    merged_df.to_csv(DOCUMENT_REGISTRY_FILE, index=False, encoding="utf-8-sig")

    audit_path = RAW_DIR / "search_pages" / "page_audit.csv"
    pd.DataFrame(page_audit).to_csv(audit_path, index=False, encoding="utf-8-sig")

    append_log(
        f"DISCOVERY DONE: old={len(old_df)}, added={len(new_df)}, "
        f"merged={len(merged_df)}"
    )


if __name__ == "__main__":
    discover()