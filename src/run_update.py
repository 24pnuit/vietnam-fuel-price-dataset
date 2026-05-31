from src.discover_documents import discover_documents
from src.fetch_document_html import fetch_document_html
from src.utils import ensure_directories, append_log


def run_update():
    ensure_directories()
    append_log("RUN_UPDATE: pipeline started")

    discover_documents()
    fetch_document_html()

    append_log("RUN_UPDATE: pipeline finished")


if __name__ == "__main__":
    run_update()