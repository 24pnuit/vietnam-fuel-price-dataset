# Bước 2 — chạy sau discover
# Dùng requests để tải HTML từng văn bản về disk.
# Lưu vào: data/raw/documents/{doc_id}.html
# Cập nhật crawl_status trong document_registry.csv

import time
import requests

from settings import (
    DOCUMENT_REGISTRY_FILE,
    RAW_DOCUMENTS_DIR,
    HEADERS,
    TIMEOUT,
    REQUEST_SLEEP,
)
from utils import ensure_directories, append_log, safe_read_csv

# Các dấu hiệu trang bị Cloudflare chặn
BLOCK_SIGNALS = [
    "just a moment", "checking your browser", "cloudflare",
    "ray id", "enable javascript", "cf-browser-verification",
]


def is_blocked(html: str) -> bool:
    low = html[:3000].lower()
    return any(sig in low for sig in BLOCK_SIGNALS)


def is_valid_detail_page(html: str) -> bool:
    low = html.lower()
    return (
        "divthuoctinh"    in low
        or "divcontentdoc" in low
        or "giá bán xăng"  in low
        or "bộ công thương" in low
        or "công văn"       in low
    )


def fetch_document_html():
    ensure_directories()

    df = safe_read_csv(DOCUMENT_REGISTRY_FILE)
    if df.empty:
        append_log("FETCH: registry rỗng → skip")
        return

    if "crawl_status" not in df.columns:
        df["crawl_status"] = "not_fetched"

    session = requests.Session()
    session.headers.update(HEADERS)

    stats = {"new": 0, "retry_ok": 0, "failed": 0, "blocked": 0, "invalid": 0, "skipped": 0}

    for idx, row in df.iterrows():
        url      = row.get("detail_url", "")
        doc_id   = row.get("doc_id", "")
        status   = str(row.get("crawl_status", "not_fetched"))

        if not url or not doc_id:
            append_log(f"FETCH SKIP: thiếu url/doc_id ở row {idx}")
            stats["failed"] += 1
            continue

        html_path = RAW_DOCUMENTS_DIR / f"{doc_id}.html"

        # File đã tải → bỏ qua
        if html_path.exists():
            df.at[idx, "crawl_status"] = "fetched"
            stats["skipped"] += 1
            continue

        # Chỉ tải những doc chưa fetched hoặc cần retry
        if status not in {"not_fetched", "fetch_failed", "blocked", "invalid_content"}:
            stats["skipped"] += 1
            continue

        is_retry = status in {"fetch_failed", "blocked", "invalid_content"}

        try:
            res = session.get(url, timeout=TIMEOUT)
            append_log(f"FETCH {res.status_code}: {url}")

            if res.status_code != 200:
                df.at[idx, "crawl_status"] = "fetch_failed"
                stats["failed"] += 1
                append_log(f"FETCH ERROR: HTTP {res.status_code} | {url}")
                time.sleep(REQUEST_SLEEP)
                continue

            html = res.text

            if is_blocked(html):
                df.at[idx, "crawl_status"] = "blocked"
                stats["blocked"] += 1
                append_log(f"FETCH BLOCKED (Cloudflare): {url}")
                time.sleep(REQUEST_SLEEP * 3)
                continue

            if not is_valid_detail_page(html):
                df.at[idx, "crawl_status"] = "invalid_content"
                stats["invalid"] += 1
                append_log(f"FETCH INVALID_CONTENT: {url}")
                time.sleep(REQUEST_SLEEP)
                continue

            html_path.write_text(html, encoding="utf-8")
            df.at[idx, "crawl_status"] = "fetched"

            if is_retry:
                stats["retry_ok"] += 1
                append_log(f"FETCH RETRY OK: {url}")
            else:
                stats["new"] += 1
                append_log(f"FETCH OK: {url}")

            time.sleep(REQUEST_SLEEP)

        except Exception as e:
            df.at[idx, "crawl_status"] = "fetch_failed"
            stats["failed"] += 1
            append_log(f"FETCH EXCEPTION: {url} | {e}")

    df.to_csv(DOCUMENT_REGISTRY_FILE, index=False, encoding="utf-8-sig")
    append_log(
        f"FETCH DONE: new={stats['new']}, retry_ok={stats['retry_ok']}, "
        f"blocked={stats['blocked']}, invalid={stats['invalid']}, "
        f"failed={stats['failed']}, skipped={stats['skipped']}"
    )


if __name__ == "__main__":
    fetch_document_html()