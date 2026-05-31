"""
parse_document_content.py — v23  (Rollback to v18 + Inline O_Muc + ESRON92 Fix)

Kiến trúc: EtLT  (Extract → lightweight-transform → Load → Transform)
═══════════════════════════════════════════════════════════════════════

Thay đổi so với v20, v21
────────────────────────
- ROLLBACK về nền tảng v18: Khắc phục lỗi `ok=0, partial=1222`. Dòng code chặn thẻ 
  `<p>` trong `<table>` của v20 đã vô tình xóa sổ toàn bộ text công văn (do website dùng table layout). 
  Quay về cơ chế `tag.get_text(" ")` của v18 để đảm bảo toàn vẹn dữ liệu.

Thay đổi mới (v23)
──────────────────
FIX-M  Thêm parser "ở mức" (v23):
    - Thêm hàm `_parse_o_muc_bog` để xử lý định dạng inline gộp nhiều mặt hàng: 
      "ở mức 0 đồng/lít xăng E5 RON92; ở mức 300 đồng/lít xăng RON95, dầu điêzen..."

FIX-N  Bổ sung Alias OCR & Phục hồi FIX-A2 (v23):
    - Bổ sung `esron92` và `r"es\s*ron\s*92"` vào E5RON92 để cứu lỗi OCR (S thay vì 5).
    - Phục hồi `FIX-A2` (remap E5 -> E5RON92), nằm an toàn trong Guard `is_post_2018` 
      để cứu BOG năm 2026 mà không làm mất rows của năm 2016.
    - Lỗi "c đồng/lít" tự động bị loại bỏ do data garbage.
    - Phục hồi keyword "khong chi" và "khoang" bị rớt ở các bản trước.
"""

import re
import unicodedata
from typing import Optional
from difflib import SequenceMatcher

import pandas as pd
from bs4 import BeautifulSoup, Tag

from config.settings import DOCUMENT_REGISTRY_FILE, RAW_DOCUMENTS_DIR, INTERIM_DIR
from src.utils import ensure_directories, append_log, safe_read_csv


OUTPUT_FILE = INTERIM_DIR / "parsed_event_prices_raw.csv"

# ── Sanity-check range cho giá xăng dầu VN ──────────────────────────────────
FUEL_PRICE_MIN = 5_000
FUEL_PRICE_MAX = 100_000


def is_valid_fuel_price(price: Optional[float]) -> bool:
    return price is not None and FUEL_PRICE_MIN <= price <= FUEL_PRICE_MAX


# ═══════════════════════════════════════════════════════════════════════════════
# Fuel & policy constants
# ═══════════════════════════════════════════════════════════════════════════════

_III_VARIANTS = r"(?:III|I\s*I\s*I|1{1,3})"

_FUEL_KEYWORDS: list[tuple[str, list[str]]] = [
    ("E5RON92",   ["e5ron92", "e5 ron92", "e5 ron 92", "sinh hoc e5ron", "r5ron92", "esron92", r"es\s*ron\s*92"]),
    ("RON95_III", [r"ron\s*9\s*5[\s-]+[i1]"]),  
    ("RON92",     ["ron92", "ron 92", "khoang"]),
    ("E5",        ["sinh hoc", "xang e5 "]),
    ("RON95",     ["ron95", "khong chi"]),
    ("DIESEL",    ["diezen", "diesel"]),
    ("MAZUT",     ["madut", "mazut"]),
]

BogRawValue = str

POLICY_PHRASES: list[tuple[str, str]] = [
    ("không trích lập quỹ",            "không trích lập"),
    ("không trích lập",                "không trích lập"),
    ("không chi sử dụng quỹ",         "không chi sử dụng"),
    ("không chi sử dụng",             "không chi sử dụng"),
    ("không chi quỹ",                 "không chi sử dụng"),
    ("không sử dụng quỹ",            "không chi sử dụng"),
    ("giữ nguyên mức trích lập",      "giữ nguyên mức trích lập"),
    ("giữ nguyên mức chi sử dụng",   "giữ nguyên mức chi sử dụng"),
    ("giữ nguyên mức",                "giữ nguyên"),
    ("giữ nguyên",                    "giữ nguyên"),
    ("như hiện hành",                 "như hiện hành"),
]

_INHERITABLE_POLICIES = {"như hiện hành", "giữ nguyên", "giữ nguyên mức trích lập", "không trích lập"}


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 1 — Text repair utilities
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_unicode(text: str) -> str:
    return unicodedata.normalize("NFC", str(text or ""))


def no_accent(s: str) -> str:
    s = unicodedata.normalize('NFC', str(s or ''))
    s = s.replace('đ', 'd').replace('Đ', 'D')
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', s).lower().strip()


_CHAR_REPAIRS: list[tuple[str, str]] = [
    (r"[Cc]h\s*[ỉi]\s+sử\s+dụng",  "chi sử dụng"),
    (r"sinh\s+h\s+ọc",              "sinh học"),   
    (r"h\s*ọ\s*c",                  "học"),
    (r"đ\s+ồ\s*n\s*g",              "đồng"),       
    (r"đ\s*ồ\s*n\s*g",              "đồng"),
    (r"[Ii]\s*í\s*t",               "lít"),
    (r"l\s*í\s*t",                  "lít"),
    (r"đồng\s*/\s*lít",             "đồng/lít"),
    (r"đồng\s*/\s*kg",              "đồng/kg"),
    (r"không\s+cao\s+h\s*ơ\s*n",    "không cao hơn"),
    (r"tr\s*í\s*ch\s+l\s*ậ\s*p",    "trích lập"),
    (r"sử\s+dụn\s*g",               "sử dụng"),
    (r"Q\s*u\s*ỹ",                  "Quỹ"),
    (r"q\s*u\s*ỹ",                  "quỹ"),
    (r"b\s*ì\s*n\s*h\s+[ổỔ]\s*n",  "bình ổn"),
    (r"hiện\s+h\s*à\s*n\s*h",       "hiện hành"),
    (r"X\s*ă\s*n\s*g",              "Xăng"),
    (r"x\s*ă\s*n\s*g",              "xăng"),
    (r"D\s*ầ\s*u",                  "Dầu"),
    (r"d\s*ầ\s*u",                  "dầu"),
    (r"kho\s*á\s*ng",               "khoáng"),
    (r"đ\s*i\s*ê\s*z?\s*e?\s*n",    "điêzen"),
    (r"d\s*i\s*ê\s*z?\s*e?\s*n",    "diêzen"),
    (r"d\s*i\s*e\s*z?\s*e?\s*n",    "diezen"),
    (r"đ\s+i\s*e\s*z?\s*e?\s*n",    "diezen"),     
    (r"đ\s+i\s*ê\s*z?\s*e?\s*n",    "điêzen"),     
    (r"[Mm]\s*a\s*d\s*ú\s*t",       "madút"),
    (r"[Mm]\s*a\s*d\s*u\s*t",       "madut"),
    (r"[Mm]\s*a\s*z\s*u\s*t",       "mazut"),
    (r"R\s*O\s*N",                  "RON"),
    (r"E\s*5(?=\s*RON)",            "E5"),
]


def _apply_char_repairs(s: str) -> str:
    for pat, repl in _CHAR_REPAIRS:
        s = re.sub(pat, repl, s, flags=re.IGNORECASE)
    return s


def repair_doc_text(text: str) -> str:
    if not text:
        return ""
    s = normalize_unicode(str(text).replace("\xa0", " "))
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = _apply_char_repairs(s)
    return s.strip()


def repair_cell(text: str) -> str:
    if not text:
        return ""
    s = normalize_unicode(str(text).replace("\xa0", " "))
    s = re.sub(r"\s+", " ", s).strip()
    s = _apply_char_repairs(s)
    return re.sub(r"\s+", " ", s).strip()


def one_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 2 — Structural normalization  (EtLT "t" layer)
# ═══════════════════════════════════════════════════════════════════════════════

def parse_number(raw: str) -> Optional[float]:
    if not raw:
        return None
    s = normalize_unicode(str(raw)).strip().replace("\xa0", "")
    if not s or s.lower() in ("none", "nan", "-", "—"):
        return None

    sign = 1.0
    if s.startswith("+"):
        s = s[1:]
    elif s.startswith("-") and len(s) > 1 and (s[1].isdigit() or s[1] == " "):
        sign = -1.0
        s = s[1:]

    for unit in ("đồng/lít,kg", "đồng/lít/kg", "đồng/lít", "đồng/kg",
                 "đồng", "/lít", "/kg", "lít", "kg", "%"):
        if s.lower().endswith(unit):
            s = s[: -len(unit)].strip()
            break

    s = s.replace(" ", "")
    if not s:
        return None

    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        return sign * float(s.replace(".", ""))
    if re.fullmatch(r"\d{1,3}(,\d{3})+", s):
        return sign * float(s.replace(",", ""))
    if re.fullmatch(r"\d+", s):
        return sign * float(s)
    try:
        return sign * float(s.replace(",", "."))
    except ValueError:
        return None


def identify_fuel_code(text: str, threshold: float = 0.82) -> Optional[str]:
    s = no_accent(text) + ' '  
    
    for code, kws in _FUEL_KEYWORDS:
        for kw in kws:
            if re.search(kw, s):
                return code
                
    best_code, best_score = None, 0.0
    for code, kws in _FUEL_KEYWORDS:
        for kw in kws:
            if '\\' in kw or '[' in kw:
                continue
            for i in range(max(1, len(s) - len(kw) + 1)):
                score = SequenceMatcher(None, s[i:i+len(kw)], kw).ratio()
                if score > best_score:
                    best_score, best_code = score, code
                    
    return best_code if best_score >= threshold else None


def detect_policy(text: str) -> Optional[str]:
    s = one_line(text).lower()
    for kw, val in POLICY_PHRASES:
        if kw in s:
            return val
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 3 — Semantic Table Parsing  (base prices)
# ═══════════════════════════════════════════════════════════════════════════════

def reconstruct_grid(table_tag: Tag) -> list[list[str]]:
    grid: dict[tuple[int, int], str] = {}
    row_idx = 0

    for tr in table_tag.find_all("tr"):
        if tr.find_parent("table") is not table_tag:
            continue

        col_idx = 0
        for cell in tr.find_all(["td", "th"], recursive=False):
            while (row_idx, col_idx) in grid:
                col_idx += 1

            raw = cell.get_text(" ", strip=False)
            text = repair_cell(re.sub(r"\s+", " ", raw).strip())

            try:
                rowspan = max(1, int(cell.get("rowspan", 1)))
                colspan = max(1, int(cell.get("colspan", 1)))
            except (ValueError, TypeError):
                rowspan = colspan = 1

            for r in range(row_idx, row_idx + rowspan):
                for c in range(col_idx, col_idx + colspan):
                    grid[(r, c)] = text

            col_idx += colspan
        row_idx += 1

    if not grid:
        return []
    max_r = max(r for r, c in grid) + 1
    max_c = max(c for r, c in grid) + 1
    return [[grid.get((r, c), "") for c in range(max_c)] for r in range(max_r)]


def is_price_table(table_tag: Tag) -> bool:
    text = repair_cell(table_tag.get_text()).lower()
    has_price = any(kw in text for kw in ["giá cơ sở", "cơ sở kỳ"])
    has_fuel  = any(kw in text for kw in
                    ["xăng", "điêzen", "diêzen", "diezen", "diesel", "madút", "madut"])
    return has_price and has_fuel and len(table_tag.find_all("tr")) >= 3


def find_current_price_col(header_rows: list[list[str]]) -> int:
    pct_cols: set[int] = set()
    for row in header_rows:
        for ci, cell in enumerate(row):
            cl = no_accent(cell)
            if re.search(r"^\s*%\s*$|chenh\s*lech\s*%|ty\s*le\s*%", cl):
                pct_cols.add(ci)

    keywords = ["ky cong bo", "cong bo", "co so ky cong"]
    for row in header_rows:
        for ci, cell in enumerate(row):
            if ci in pct_cols:
                continue
            
            cl_no_acc = no_accent(cell)
            if any(kw in cl_no_acc for kw in keywords):
                return ci

    return 3 if 2 in pct_cols else 2


def count_header_rows(grid: list[list[str]]) -> int:
    for i, row in enumerate(grid):
        if not row:
            continue
        clean = re.sub(r"^\d+[.\s]+", "", row[0]).strip()
        fuel  = identify_fuel_code(clean) or identify_fuel_code(row[0])
        if not fuel:
            continue
        has_price = any(
            is_valid_fuel_price(parse_number(cell))
            for cell in row[1:]
            if cell.strip()
        )
        if has_price:
            return i
    return 1


def extract_base_prices_from_table(
    table_tag: Tag,
    doc_id: str = "",
) -> dict[str, dict]:
    grid = reconstruct_grid(table_tag)
    if len(grid) < 3:
        return {}

    n_hdr     = count_header_rows(grid)
    headers   = grid[:n_hdr]
    data_rows = grid[n_hdr:]
    curr_col  = find_current_price_col(headers)

    unit_raw = "đồng/lít,kg"
    for row in headers:
        for cell in row:
            if "đồng/lít" in cell.lower():
                unit_raw = "đồng/lít,kg"
                break

    result: dict[str, dict] = {}

    for row in data_rows:
        if not row or not row[0].strip():
            continue

        raw_name   = row[0].strip()
        clean_name = re.sub(r"^\d+[.\s]+", "", raw_name).strip()
        fuel_code  = identify_fuel_code(clean_name) or identify_fuel_code(raw_name)
        if not fuel_code or fuel_code in result:
            continue

        price_raw = row[curr_col].strip() if curr_col < len(row) else ""
        price     = parse_number(price_raw)

        if not is_valid_fuel_price(price):
            for alt in [curr_col + 1, curr_col - 1, 2, 3]:
                if 0 <= alt < len(row) and alt != curr_col:
                    p = parse_number(row[alt])
                    if is_valid_fuel_price(p):
                        price_raw, price = row[alt].strip(), p
                        break

        if not is_valid_fuel_price(price):
            append_log(
                f"PARSE v23 WARNING [{doc_id}]: "
                f"no valid price for {fuel_code} (raw='{price_raw}')"
            )
            continue

        result[fuel_code] = {
            "fuel_type_raw":     repair_cell(clean_name),
            "base_price_raw":    price_raw,
            "base_price":        price,
            "unit_raw":          unit_raw,
            "extraction_method": "table",
        }

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 4 — Section slicing  (operates on repair_doc_text output)
# ═══════════════════════════════════════════════════════════════════════════════

def find_position(text: str, patterns: list[str], start: int = 0) -> int:
    best: Optional[int] = None
    for pat in patterns:
        m = re.search(pat, text[start:], re.IGNORECASE | re.DOTALL)
        if m:
            pos = start + m.start()
            if best is None or pos < best:
                best = pos
    return -1 if best is None else best


def slice_section(
    text: str,
    start_patterns: list[str],
    end_patterns: list[str],
    after: int = 0,
) -> str:
    s = find_position(text, start_patterns, after)
    if s == -1:
        return ""
    e = find_position(text, end_patterns, s + 1)
    return text[s: (e if e != -1 else len(text))].strip()


def decision_start(text: str) -> int:
    return max(0, find_position(text, [
        r"Bộ\s+Công\s+Thương\s+công\s+bố\s+giá\s+cơ\s+sở",
        r"Liên\s+Bộ\s+Công\s+Thương\s*[-–]\s*Tài\s+chính\s+công\s+bố\s+giá\s+cơ\s+sở",
        r"công\s+bố\s+giá\s+cơ\s+sở\s+các\s+mặt\s+hàng\s+xăng\s+dầu",
        r"mặt\s+hàng\s+xăng\s+dầu\s+tiêu\s+dùng\s+phổ\s+biến.*?như\s+sau",
        r"(?:^|\n)Liên\s+Bộ\s+Công\s+Thương\s*[-–]\s*Tài\s+chính\s+thông\s+báo\s+(?:giá\s+cơ\s+sở|mức\s+giá)",
        r"(?:^|\n)Bộ\s+Tài\s+chính\s*[-–]\s*Bộ\s+Công\s+Thương\s+thông\s+báo\s+(?:giá\s+cơ\s+sở|mức\s+giá)",
        r"(?:^|\n)Bộ\s+Công\s+Thương\s+thông\s+báo\s+(?:giá\s+cơ\s+sở|mức\s+giá)",
        r"(?:^|\n)thông\s+báo\s+giá\s+cơ\s+sở\s+các\s+mặt\s+hàng\s+xăng\s+dầu",
    ], 0))


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 6 — Event date extraction  (FIX-A)
# ═══════════════════════════════════════════════════════════════════════════════

def parse_event_date(soup: BeautifulSoup, full_text: str) -> Optional[str]:
    for label_cell in soup.find_all(["td", "th"]):
        cell_text = label_cell.get_text(" ", strip=True).lower()
        if "ngày ban hành" not in cell_text:
            continue
        tr = label_cell.find_parent("tr")
        if not tr:
            continue

        cells = tr.find_all(["td", "th"])
        for i, c in enumerate(cells):
            if "ngày ban hành" in c.get_text(" ", strip=True).lower():
                if i + 1 < len(cells):
                    val = cells[i + 1].get_text(" ", strip=True)
                    m = re.search(r"\d{1,2}/\d{1,2}/\d{4}", val)
                    if m:
                        return m.group()
                break

        next_tr = tr.find_next_sibling("tr")
        if next_tr:
            val = next_tr.get_text(" ", strip=True)
            m = re.search(r"\d{1,2}/\d{1,2}/\d{4}", val)
            if m:
                return m.group()

    for tag in soup.find_all(["p", "div", "td"]):
        collapsed = one_line(tag.get_text(" ", strip=False))
        if "hà nội" not in collapsed.lower():
            continue
        m = re.search(
            r"Hà\s+Nội\s*,\s*ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})",
            collapsed, re.IGNORECASE,
        )
        if m:
            d, mo, yr = m.groups()
            return f"{int(d):02d}/{int(mo):02d}/{yr}"

    targets = [full_text, one_line(full_text)]
    patterns: list[tuple[str, int]] = [
        (r"(?:^|[,;\s])ngày\s+(\d{1,2}/\d{1,2}/\d{4})",                              1),
        (r"[Áá]p\s+dụng\s+từ.*?ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", 3),
        (r"giá\s+cơ\s+sở\s+kỳ\s+công\s+bố\s*,\s*ngày\s*(\d{1,2}/\d{1,2}/\d{4})",   1),
        (r"kể\s+từ\s+\d+\s+giờ\s+\d*\s*ngày\s+(\d{1,2}/\d{1,2}/\d{4})",            1),
        (r"kể\s+từ\s+\d+\s+giờ\s+(\d{1,2})/(\d{1,2})/(\d{4})",                      3),
        (r"(\d{4})-(\d{2})-(\d{2})",                                                  -1),
    ]
    for target in targets:
        for pat, n in patterns:
            m = re.search(pat, target, re.IGNORECASE | re.DOTALL)
            if not m:
                continue
            if n == 1:
                return m.group(1)
            if n == 3:
                d, mo, yr = m.groups()[:3]
                return f"{int(d):02d}/{int(mo):02d}/{yr}"
            if n == -1:
                yr, mo, d = m.groups()[:3]
                return f"{int(d):02d}/{int(mo):02d}/{yr}"

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 7 — Bullet-pattern regex  (retail + BOG)
# ═══════════════════════════════════════════════════════════════════════════════

_BULLET_RETAIL = re.compile(
    r"[-–•]\s*"
    r"(?P<fuel>[^:;：；\n]{3,80}?)"
    r"\s*[:;：；]\s*"
    r"(?:không\s+cao\s+h\w*\s+)?"
    r"(?P<price>\d[\d\s.,]*)"
    r"\s*đồng\s*/\s*(?P<unit>lít|kg)",
    re.IGNORECASE,
)

_BULLET_BOG = re.compile(
    r"[-–•+]\s*"
    r"(?P<fuel>[^:;：；\n]{3,80}?)"
    r"\s*[:;：；]\s*"
    r"(?P<value>"
        r"\d[\d\s.,]*"
        r"|không\s+trích\s+lập(?:\s+quỹ)?"
        r"|không\s+chi\s+sử\s+dụng(?:\s+quỹ)?"
        r"|giữ\s+nguyên(?:\s+mức(?:\s+trích\s+lập|\s+chi\s+sử\s+dụng)?)?"
        r"|như\s+hiện\s+hành"
    r")"
    r"(?:\s*đồng\s*/\s*(?:lít|kg))?",
    re.IGNORECASE,
)

_NO_BULLET_BOG = re.compile(
    r"(?:^|\n)\s*"
    r"(?P<fuel>[^:;：；\n]{3,80}?)"
    r"\s*[:;：；]\s*"
    r"(?P<value>\d[\d\s.,]*)"
    r"\s*đồng\s*/\s*(?:lít|kg)",
    re.IGNORECASE | re.MULTILINE,
)

_INLINE_BOG_PATTERNS: list[tuple[str, list[str]]] = [
    ("E5RON92",   [
        r"(?<!\w)(\d[\d\s.,]*)\s*đồng\s*/\s*lít\s*xăng\s+E5RON92",
        r"(?<!\w)(\d[\d\s.,]*)\s*đồng\s*/\s*lít\s*xăng\s+E5\s*RON\s*92",
    ]),
    ("RON95_III", [
        rf"(?<!\w)(\d[\d\s.,]*)\s*đồng\s*/\s*lít\s*xăng\s+RON\s*95\s*[-–\s]\s*{_III_VARIANTS}",
    ]),
    ("RON92",     [
        r"(?<!\w)(\d[\d\s.,]*)\s*đồng\s*/\s*lít\s*xăng\s+khoáng",
        r"(?<!\w)(\d[\d\s.,]*)\s*đồng\s*/\s*lít\s*xăng\s+RON\s*92(?!\s*[-–])",
    ]),
    ("E5",        [
        r"(?<!\w)(\d[\d\s.,]*)\s*đồng\s*/\s*lít\s*xăng\s+E5\b(?!\s*RON)",
        r"(?<!\w)(\d[\d\s.,]*)\s*đồng\s*/\s*lít\s*xăng\s+sinh\s+học",
    ]),
    ("RON95",     [
        r"(?<!\w)(\d[\d\s.,]*)\s*đồng\s*/\s*lít\s*xăng\s+RON\s*95(?!\s*[-–])",
    ]),
    ("DIESEL",    [
        r"(?<!\w)(\d[\d\s.,]*)\s*đồng\s*/\s*lít\s*(?:dầu\s+)?(?:điêzen|diêzen|diezen)",
    ]),
    ("MAZUT",     [
        r"(?<!\w)(\d[\d\s.,]*)\s*đồng\s*/\s*kg\s*(?:dầu\s+)?(?:mad[uú]t|mazut)",
    ]),
]


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 8 — Text-based extraction  (retail + BOG)
# ═══════════════════════════════════════════════════════════════════════════════

def extract_retail_from_text(text: str) -> dict[str, dict]:
    ds    = decision_start(text)
    block = slice_section(
        text,
        [r"2\s*\.\s*Giá\s+bán\s+xăng\s+dầu",
         r"Giá\s+bán\s+xăng\s+dầu",
         r"Giá\s+bán\s+các\s+mặt\s+hàng\s+xăng\s+dầu"],
        [r"3\s*\.\s*Thời\s+gian\s+thực\s+hiện",
         r"Thời\s+gian\s+thực\s+hiện",
         r"Bộ\s+Công\s+Thương\s+thông\s+báo",
         r"Nơi\s+nhận"],
        after=ds,
    )
    if not block:
        return {}

    result: dict[str, dict] = {}
    for m in _BULLET_RETAIL.finditer(block):
        raw_fuel  = repair_cell(m.group("fuel"))
        fuel_code = identify_fuel_code(raw_fuel)
        if not fuel_code or fuel_code in result:
            continue
        price_raw = m.group("price").strip()
        price     = parse_number(price_raw)
        unit      = f"đồng/{m.group('unit')}"
        if is_valid_fuel_price(price):
            result[fuel_code] = {
                "fuel_type_raw":     raw_fuel,
                "retail_price_raw":  price_raw,
                "retail_price":      price,
                "unit_raw":          unit,
                "extraction_method": "text",
            }

    return result


def _parse_o_muc_bog(block: str) -> dict[str, str]:
    """
    Parse format inline nhiều fuel trên 1 mức giá:
    "ở mức 0 đồng/lít xăng E5 RON92; ở mức 300 đồng/lít xăng RON95, dầu điêzen; ..."
    """
    result: dict[str, str] = {}
    _O_MUC = re.compile(
        r"ở\s+mức\s+"
        r"(?P<value>\d[\d\s.,]*)"
        r"\s*đồng\s*/\s*(?:lít|kg)"
        r"(?P<fuels>[^;.]+)",
        re.IGNORECASE,
    )
    for m in _O_MUC.finditer(block):
        value     = m.group("value").strip()
        fuels_raw = m.group("fuels")
        for part in re.split(r"[,]", fuels_raw):
            part = repair_cell(part.strip())
            if not part:
                continue
            fuel_code = identify_fuel_code(part)
            if fuel_code:
                result.setdefault(fuel_code, value)
    return result


def _parse_bog_block(block: str) -> dict[str, BogRawValue]:
    if not block:
        return {}

    policy   = detect_policy(block)
    has_nums = bool(re.search(r"\d{2,}", block))
    if policy and not has_nums:
        return {code: policy for code, _ in _FUEL_KEYWORDS}

    result: dict[str, BogRawValue] = {}

    for m in _BULLET_BOG.finditer(block):
        raw_fuel  = repair_cell(m.group("fuel"))
        fuel_code = identify_fuel_code(raw_fuel)
        if not fuel_code or fuel_code in result:
            continue
        raw_val   = m.group("value").strip()
        seg_pol   = detect_policy(raw_val)
        result[fuel_code] = seg_pol if seg_pol else raw_val

    if result and policy:
        for code, _ in _FUEL_KEYWORDS:
            result.setdefault(code, policy)

    if result:
        return result

    o_muc = _parse_o_muc_bog(block)
    if o_muc:
        return o_muc

    if not result:
        for m in _NO_BULLET_BOG.finditer(block):
            raw_fuel  = repair_cell(m.group("fuel"))
            fuel_code = identify_fuel_code(raw_fuel)
            if not fuel_code or fuel_code in result:
                continue
            raw_val = m.group("value").strip()
            seg_pol = detect_policy(raw_val)
            result[fuel_code] = seg_pol if seg_pol else raw_val

    if result:
        return result

    for fuel_code, pats in _INLINE_BOG_PATTERNS:
        if fuel_code in result:
            continue
        for pat in pats:
            m = re.search(pat, block, re.IGNORECASE | re.DOTALL)
            if m:
                val = m.group(1).strip()
                val = re.sub(r"[^\d.,\s].*$", "", val).strip()
                if val:
                    result.setdefault(fuel_code, val)
                break
    
    if policy and has_nums:
        for code, _ in _FUEL_KEYWORDS:
            result.setdefault(code, policy)

    return result


def is_valid_bog_block(block: str) -> bool:
    if not block:
        return False
    s = block.lower()
    has_money  = bool(re.search(r"\d+\s*đồng\s*/\s*(?:lít|kg)", s))
    has_policy = any(kw in s for kw, _ in POLICY_PHRASES)
    return not ("áp dụng từ" in s and not has_money and not has_policy)


def parse_bog_sections(text: str) -> tuple[dict[str, BogRawValue], dict[str, BogRawValue]]:
    ds = decision_start(text)

    contrib_block = slice_section(
        text,
        [r"1\s*\.\s*1\s*\.\s*Trích\s+lập\s+Quỹ\s+[Bb]ình\s+ổn",
         r"Trích\s+lập\s+Quỹ\s+[Bb]ình\s+ổn",
         r"[Mm]ức\s+trích\s+lập\s+Quỹ",
         r"[Gg]iữ\s+nguyên\s+mức\s+trích\s+lập\s+Quỹ",
         r"[Kk]hông\s+trích\s+lập\s+[Qq]uỹ"],
        [r"1\s*\.\s*2\s*\.\s*[Cc]hi\s+sử\s+dụng",
         r"[Cc]hi\s+sử\s+dụng\s+Quỹ",
         r"2\s*\.\s*Giá\s+bán\s+xăng\s+dầu"],
        after=ds,
    )

    spend_block = slice_section(
        text,
        [r"1\s*\.\s*2\s*\.\s*[Cc]hi\s+sử\s+dụng\s+Quỹ\s+[Bb]ình\s+ổn",
         r"1\s*\.\s*2\s*\.\s*[Cc]hi\s+sử\s+dụng",
         r"[Cc]hi\s+sử\s+dụng\s+Quỹ\s+[Bb]ình\s+ổn\s+giá\s+xăng\s+dầu\s+đối\s+với",
         r"[Mm]ức\s+chi\s+sử\s+dụng\s+Quỹ",
         r"[Kk]hông\s+chi\s+[Ss]ử\s+dụng\s+[Qq]uỹ",
         r"[-–]\s*[Cc]hi\s+sử\s+dụng\s+Quỹ\s+[Bb]ình\s+ổn"],
        [r"2\s*\.\s*Giá\s+bán\s+xăng\s+dầu",
         r"3\s*\.\s*Thời\s+gian\s+thực\s+hiện"],
        after=ds,
    )

    if spend_block and not is_valid_bog_block(spend_block):
        spend_block = ""

    contrib_map = _parse_bog_block(contrib_block)
    spend_map   = _parse_bog_block(spend_block)

    if not spend_map:
        tail = text[ds:].lower()
        for phrase in ("không chi sử dụng quỹ bình ổn",
                       "không chi quỹ bình ổn",
                       "không sử dụng quỹ bình ổn"):
            if phrase in tail:
                spend_map = {code: "không chi sử dụng" for code, _ in _FUEL_KEYWORDS}
                break

    for fuel_code, contrib_val in contrib_map.items():
        if fuel_code not in spend_map and contrib_val in _INHERITABLE_POLICIES:
            spend_map[fuel_code] = "như hiện hành"

    return contrib_map, spend_map


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 9 — HTML document extraction
# ═══════════════════════════════════════════════════════════════════════════════

def extract_main_content(html: str) -> tuple[BeautifulSoup, str, list[Tag]]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    candidates = [
        soup.find(id="divContentDoc"),
        soup.find(id="divNoiDung"),
        soup.find(id="contentdoc"),
        soup.find("div", class_="content1"),
        soup.find("div", class_="content"),
    ]
    main = next(
        (c for c in candidates if c and len(c.get_text(" ", strip=True)) > 500),
        None,
    ) or soup.body or soup

    BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"}
    lines = []
    
    for tag in main.find_all(BLOCK_TAGS):
        if any(hasattr(c, 'name') and c.name in BLOCK_TAGS for c in tag.children):
            continue
            
        line = repair_cell(tag.get_text(" "))   
        if line:
            lines.append(line)
            
    text = "\n".join(lines)
    text = normalize_unicode(text)

    for marker in ("BỘ CÔNG THƯƠNG", "LIÊN BỘ CÔNG THƯƠNG",
                   "Liên Bộ Công Thương", "Số:"):
        pos = text.find(marker)
        if pos != -1:
            text = text[pos:]
            break

    for marker in ("THƯ VIỆN PHÁP LUẬT", "Gửi góp ý",
                   "Hãy để chúng tôi", "Cloudflare"):
        pos = text.find(marker)
        if pos != -1:
            text = text[:pos]
            break

    text   = repair_doc_text(text)
    tables = main.find_all("table")

    return soup, text, tables


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 10 — Document orchestration
# ═══════════════════════════════════════════════════════════════════════════════

def parse_one_document(row: pd.Series) -> list[dict]:
    doc_id    = one_line(str(row.get("doc_id", "")))
    html_path = RAW_DOCUMENTS_DIR / f"{doc_id}.html"

    if not html_path.exists():
        append_log(f"PARSE v23 SKIP: html not found for doc_id={doc_id}")
        return []

    html = html_path.read_text(encoding="utf-8", errors="ignore")

    soup, text, tables = extract_main_content(html)
    event_date_raw = parse_event_date(soup, text)

    base_map: dict[str, dict] = {}
    for tbl in tables:
        if is_price_table(tbl):
            base_map = extract_base_prices_from_table(tbl, doc_id=doc_id)
            if base_map:
                break

    retail_map = extract_retail_from_text(text)
    contribution_map, spending_map = parse_bog_sections(text)

    event_dt = pd.to_datetime(event_date_raw, format="%d/%m/%Y", errors="coerce")
    is_post_2018 = (event_dt >= pd.Timestamp("2018-01-01")) if pd.notna(event_dt) else True
    
    if is_post_2018:
        # FIX-A: "Xăng RON95"/"Xăng không chì" → RON95 → remap → RON95_III
        if "RON95_III" in (base_map | retail_map):
            for bog_map in [contribution_map, spending_map]:
                if "RON95" in bog_map and "RON95_III" not in bog_map:
                    bog_map["RON95_III"] = bog_map.pop("RON95")
                    
        # FIX-A2: "Xăng sinh học"/"Xăng E5" → E5 → remap → E5RON92
        if "E5RON92" in (base_map | retail_map):
            for bog_map in [contribution_map, spending_map]:
                if "E5" in bog_map and "E5RON92" not in bog_map:
                    bog_map["E5RON92"] = bog_map.pop("E5")

    found_fuels = set(base_map) | set(retail_map)
    rows: list[dict] = []

    for fuel_code in sorted(found_fuels):
        base_info   = base_map.get(fuel_code, {})
        retail_info = retail_map.get(fuel_code, {})

        fuel_type_raw = (
            retail_info.get("fuel_type_raw")
            or base_info.get("fuel_type_raw")
            or ""
        )
        if not fuel_type_raw:
            continue

        base_price_raw       = base_info.get("base_price_raw")
        base_price           = base_info.get("base_price")
        retail_price_raw     = retail_info.get("retail_price_raw")
        retail_price         = retail_info.get("retail_price")
        
        bog_contribution_raw: Optional[BogRawValue] = contribution_map.get(fuel_code)
        bog_spending_raw:     Optional[BogRawValue] = spending_map.get(fuel_code)

        unit_raw = retail_info.get("unit_raw") or base_info.get("unit_raw") or ""
        extraction_method = (
            "table+text" if base_info and retail_info
            else "table"  if base_info
            else "text"
        )

        missing = [f for f, v in [
            ("event_date_raw",       event_date_raw),
            ("base_price_raw",       base_price_raw),
            ("retail_price_raw",     retail_price_raw),
            ("bog_contribution_raw", bog_contribution_raw),
            ("bog_spending_raw",     bog_spending_raw),
        ] if not v]

        rows.append({
            "doc_id":                doc_id,
            "event_date_raw":        event_date_raw,
            "fuel_type_raw":         fuel_type_raw,
            "fuel_code_candidate":   fuel_code,
            "base_price_raw":        base_price_raw,
            "base_price":            base_price,
            "retail_price_raw":      retail_price_raw,
            "retail_price":          retail_price,
            "bog_contribution_raw":  bog_contribution_raw,
            "bog_spending_raw":      bog_spending_raw,
            "unit_raw":              unit_raw,
            "extraction_method":     extraction_method,
            "parse_status":          "parsed_ok" if not missing else "parsed_partial",
            "missing_fields":        ";".join(missing),
        })

    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

def parse_document_content():
    ensure_directories()
    append_log("PARSE v23 (Rollback to v18 + Inline O_Muc + ESRON92 Fix + Guards): start")

    registry = safe_read_csv(DOCUMENT_REGISTRY_FILE)
    if registry.empty:
        append_log("PARSE v23: registry empty → skip")
        return
    if "doc_id" not in registry.columns:
        append_log("PARSE v23 ERROR: missing doc_id column")
        return

    all_rows: list[dict] = []
    docs_with_html = docs_parsed = 0

    for _, row in registry.iterrows():
        doc_id    = one_line(str(row.get("doc_id", "")))
        html_path = RAW_DOCUMENTS_DIR / f"{doc_id}.html"
        if not html_path.exists():
            continue
        docs_with_html += 1
        try:
            parsed = parse_one_document(row)
            if parsed:
                all_rows.extend(parsed)
                docs_parsed += 1
        except Exception as e:
            append_log(f"PARSE v23 ERROR: doc_id={doc_id} | {e}")

    if not all_rows:
        append_log("PARSE v23: no parsed rows")
        return

    output_df = pd.DataFrame(all_rows)
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)

    try:
        output_df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    except PermissionError:
        fb = OUTPUT_FILE.with_name(OUTPUT_FILE.stem + "_new.csv")
        output_df.to_csv(fb, index=False, encoding="utf-8-sig")
        append_log(f"PARSE v23 WARNING: output locked → {fb}")

    n_ok      = (output_df["parse_status"] == "parsed_ok").sum()
    n_partial = (output_df["parse_status"] == "parsed_partial").sum()
    n_table   = output_df["extraction_method"].str.contains("table", na=False).sum()
    n_text    = (output_df["extraction_method"] == "text").sum()

    def _is_policy(x) -> bool:
        if pd.isna(x):
            return False
        s = str(x).replace(".", "").replace(",", "").replace("+", "").replace("-", "").replace(" ", "")
        return not s.isdigit()

    n_pol_c = output_df["bog_contribution_raw"].apply(_is_policy).sum()
    n_pol_s = output_df["bog_spending_raw"].apply(_is_policy).sum()

    append_log(
        f"PARSE v23 DONE: docs_with_html={docs_with_html}, "
        f"docs_parsed={docs_parsed}, rows={len(output_df)}, "
        f"ok={n_ok}, partial={n_partial}"
    )
    append_log(
        f"PARSE v23 METHOD: table_rows={n_table}, text_only={n_text}"
    )
    append_log(
        f"PARSE v23 BOG: policy_contrib={n_pol_c}, policy_spend={n_pol_s}"
    )
    append_log(f"PARSE v23 OUTPUT: {OUTPUT_FILE}")


if __name__ == "__main__":
    parse_document_content()