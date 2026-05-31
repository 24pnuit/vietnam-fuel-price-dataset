import time
import requests

from config.settings import (
    DOCUMENT_REGISTRY_FILE,
    RAW_DOCUMENTS_DIR,
    HEADERS,
    TIMEOUT,
    REQUEST_SLEEP,
)
from src.utils import ensure_directories, append_log, safe_read_csv


def is_valid_detail_page(html: str) -> bool:
    lowered = html.lower()
    return (
        "divthuoctinh" in lowered
        or "divcontentdoc" in lowered
        or "giá bán xăng dầu" in lowered
        or "bộ công thương" in lowered
        or "công văn" in lowered
    )


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def fetch_document_html():
    ensure_directories()

    df = safe_read_csv(DOCUMENT_REGISTRY_FILE)

    if df.empty:
        append_log("FETCH: registry empty → skip")
        return

    # đảm bảo có cột crawl_status
    if "crawl_status" not in df.columns:
        df["crawl_status"] = "not_fetched"

    session = build_session()

    new_fetched = 0
    retry_success = 0
    retry_failed = 0
    invalid = 0
    skipped_fetched = 0

    for idx, row in df.iterrows():
        url = row.get("detail_url")
        doc_id = row.get("doc_id")
        crawl_status = str(row.get("crawl_status", "not_fetched"))

        if not url or not doc_id:
            df.at[idx, "crawl_status"] = "fetch_failed"
            retry_failed += 1
            append_log(f"FETCH SKIP: missing url/doc_id at row {idx}")
            continue

        file_path = RAW_DOCUMENTS_DIR / f"{doc_id}.html"

        # nếu file đã có thì coi như fetched
        if file_path.exists():
            df.at[idx, "crawl_status"] = "fetched"
            skipped_fetched += 1
            continue

        is_retry = crawl_status in {"fetch_failed", "blocked", "invalid_content"}

        try:
            res = session.get(url, timeout=TIMEOUT)
            append_log(f"FETCH STATUS: {res.status_code} | {url}")

            if res.status_code != 200:
                df.at[idx, "crawl_status"] = "fetch_failed"
                if is_retry:
                    retry_failed += 1
                else:
                    retry_failed += 1
                append_log(f"FETCH ERROR: HTTP {res.status_code} | {url}")
                time.sleep(REQUEST_SLEEP)
                continue

            html = res.text

            if not is_valid_detail_page(html):
                df.at[idx, "crawl_status"] = "invalid_content"
                invalid += 1
                append_log(f"FETCH INVALID_CONTENT: {url}")
                time.sleep(REQUEST_SLEEP)
                continue

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(html)

            df.at[idx, "crawl_status"] = "fetched"

            if is_retry:
                retry_success += 1
                append_log(f"FETCH RETRY SUCCESS: {url}")
            else:
                new_fetched += 1
                append_log(f"FETCH NEW OK: {url}")

            time.sleep(REQUEST_SLEEP)

        except Exception as e:
            df.at[idx, "crawl_status"] = "fetch_failed"
            retry_failed += 1
            append_log(f"FETCH EXCEPTION: {url} | {e}")

    df.to_csv(DOCUMENT_REGISTRY_FILE, index=False, encoding="utf-8-sig")

    append_log(
        "FETCH DONE: "
        f"new_fetched={new_fetched}, "
        f"retry_success={retry_success}, "
        f"retry_failed={retry_failed}, "
        f"invalid={invalid}, "
        f"already_had_file={skipped_fetched}"
    )


if __name__ == "__main__":
    fetch_document_html()