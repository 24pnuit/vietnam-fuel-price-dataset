import re
import unicodedata
from typing import Optional
from difflib import SequenceMatcher

import pandas as pd
from bs4 import BeautifulSoup, Tag, NavigableString

from settings import (
    DOCUMENT_REGISTRY_FILE,
    PARSED_DOCUMENTS_FILE,
    RAW_DOCUMENTS_DIR,
    INTERIM_DIR,
)
from utils import ensure_directories, append_log, safe_read_csv


# Giữ nguyên file output của pipeline cũ để không phá run_pipeline.bat.
# Nhưng schema/các thuộc tính bên trong giữ theo logic parser mới.
OUTPUT_FILE = PARSED_DOCUMENTS_FILE
VCB_OUTPUT_FILE = INTERIM_DIR / "vcb_sell_rates_all.csv"

PARSED_COLUMNS = [
    "doc_id",
    "event_date_raw",
    "fuel_type_raw",
    "fuel_code_candidate",
    "base_price_raw",
    "base_price",
    "retail_price_raw",
    "retail_price",
    "bog_contribution_raw",
    "bog_spending_raw",
    "vcb_rate_raw",
    "vcb_rate",
    "unit_raw",
    "extraction_method",
    "parse_status",
    "missing_fields",
]

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
    (r"s\s+ử\s+dụng", "sử dụng"),
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
    (r"RON\s*95\s*-\s*I\s*I\s*I", "RON95-III"),
    (r"1\s+8\s+0\s*CST", "180CST"),
    (r"RON\s*95\s*-\s*III", "RON95-III"),
    (r"180\s+CST", "180CST"),
    (r"madút\s+1\s+8\s+0", "madút 180"),
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


def p_to_clean_text(tag: Tag) -> str:
    """
    Collapse tất cả text nodes trong 1 block tag (<p>, <li>...) thành 1 string sạch.
    Nguyên tắc: chỉ insert space tại ranh giới TỪ, không phải ranh giới tag.
    """
    parts = []
    for node in tag.descendants:
        if not isinstance(node, NavigableString): continue
        s = unicodedata.normalize('NFC', str(node)).replace('\xa0', ' ').replace('\n', ' ')
        if not s.strip():
            if parts and not parts[-1].endswith(' '):
                parts.append(' ')
            continue
        parts.append(s)
    
    result = ''
    for part in parts:
        if not result: 
            result = part
            continue
        prev_end   = result.rstrip(' ')[-1] if result.rstrip(' ') else ''
        part_strip = part.lstrip(' ')
        next_start = part_strip[0] if part_strip else ''
        has_space  = result.endswith(' ') or part.startswith(' ')
        
        is_char_boundary = (
            not has_space and prev_end and next_start and
            (prev_end.isalnum() or prev_end in '-–/.') and
            (next_start.isalnum() or next_start in '-–/.')
        )
        if is_char_boundary: 
            result = result + part_strip
        elif has_space:      
            result = result.rstrip(' ') + ' ' + part.lstrip(' ')
        else:                
            result = result + part
    return re.sub(r'  +', ' ', result).strip()


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

    # Xóa sạch khoảng trắng OCR để gom cụm số chính xác
    s = s.replace(" ", "")
    if not s:
        return None

    # ─── VÁ LỖI TỶ GIÁ VCB KỲ NĂM 2026 (Format: 24.531.00 -> 24531.0) ───
    if re.fullmatch(r"\d{1,3}\.\d{3}\.\d{2}", s):
        return sign * float(s[:-3].replace(".", ""))
    # ──────────────────────────────────────────────────────────────────

    # VN format: 24.430,00
    if re.fullmatch(r"\d{1,3}(\.\d{3})+,\d+", s):
        return sign * float(
            s.replace(".", "").replace(",", ".")
        )
    # US format: 24,430.00
    if re.fullmatch(r"\d{1,3}(,\d{3})+\.\d+", s):
        return sign * float(s.replace(",", ""))
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
# Layer 3 — Semantic Table Parsing  (base prices & VCB)
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
    has_price = any(kw in text for kw in ["giá cơ sở", "cơ sở kỳ", "giá c ơ sở", "chênh lệch"])
    has_fuel  = any(kw in text for kw in ["xăng", "điêzen", "diêzen", "diezen", "diesel", "madút", "madut"])
    return has_price and has_fuel and len(table_tag.find_all("tr")) >= 3


def is_vcb_table(table_tag):
    text = re.sub(
        r"\s+",
        "",
        no_accent(table_tag.get_text(" ", strip=True))
    )

    return (
        "vcb" in text
        and ("ban" in text or "mua" in text)
    )

def extract_vcb_rate(table_tag: Tag) -> Optional[str]:
    VCB_MIN, VCB_MAX = 15_000, 30_000

    grid = reconstruct_grid(table_tag)
    if not grid:
        return None

    vcb_ban_col: Optional[int] = None
    n_header = 0

    for r, row in enumerate(grid[:5]):

        for c, cell in enumerate(row):

            txt = re.sub(r"\s+", "", no_accent(cell))

            if "ban" not in txt:
                continue

            window = []

            for rr in range(max(0, r - 2), r + 1):
                for cc in range(max(0, c - 2), c + 3):

                    if rr < len(grid) and cc < len(grid[rr]):
                        window.append(
                            re.sub(r"\s+", "", no_accent(grid[rr][cc]))
                        )

            if any("vcb" in x for x in window):
                vcb_ban_col = c
                n_header = r + 1
                break

        if vcb_ban_col is not None:
            break

    if vcb_ban_col is None:
        return None

    data_rows = grid[n_header:]
    if not data_rows:
        return None

    for row in data_rows:
        first = row[0].lower() if len(row) > 0 else ""
        second = row[1].lower() if len(row) > 1 else ""

        if any(
            kw in first + second
            for kw in ["trung", "tb", "bquân", "bq", "quân", "average"]
        ):
            if vcb_ban_col < len(row):
                raw = row[vcb_ban_col].strip()
                val = parse_number(raw)
                print("FAILED:", raw, val)

                if val and VCB_MIN <= val <= VCB_MAX:
                    print("RETURN:", repr(raw))
                    return raw

    for row in reversed(data_rows):
        if vcb_ban_col < len(row):
            raw = row[vcb_ban_col].strip()
            val = parse_number(raw)
            print("FAILED:", raw, val)
            if val and VCB_MIN <= val <= VCB_MAX:
                print("RETURN:", repr(raw))
                return raw

    return None


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
                f"PARSE v24 WARNING [{doc_id}]: "
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
        r"Bộ\s+Công\s+Thương\s+công\s+bố\s+giá\s+cơ\s+sở\s+các\s+mặt\s+hàng",
        r"Liên\s+Bộ\s+Công\s+Thương\s*[-–]\s*Tài\s+chính\s+công\s+bố\s+giá\s+cơ\s+sở\s+các\s+mặt\s+hàng",
        r"công\s+bố\s+giá\s+cơ\s+sở\s+các\s+mặt\s+hàng\s+xăng\s+dầu",
        r"mặt\s+hàng\s+xăng\s+dầu\s+tiêu\s+dùng\s+phổ\s+biến.*?như\s+sau",
        r"Liên\s+Bộ\s+Công\s+Thương\s*[-–]\s*Tài\s+chính\s+công\s+bố\s+giá\s+cơ\s+sở.*?như\s+sau",
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
        [r"[-–]\s*[Cc]hi\s+sử\s+dụng\s+quỹ\s+bình\s+ổn",
         r"1\s*\.\s*2\s*\.\s*[Cc]hi\s+sử\s+dụng\s+Quỹ\s+[Bb]ình\s+ổn",
         r"1\s*\.\s*2\s*\.\s*[Cc]hi\s+sử\s+dụng",
         r"[Cc]hi\s+sử\s+dụng\s+Quỹ\s+[Bb]ình\s+ổn\s+giá\s+xăng\s+dầu\s+đối\s+với",
         r"[Mm]ức\s+chi\s+sử\s+dụng\s+Quỹ",
         r"[Kk]hông\s+chi\s+[Ss]ử\s+dụng\s+[Qq]uỹ",
         r"[-–]\s*[Cc]hi\s+sử\s+dụng\s+Quỹ\s+[Bb]ình\s+ổn"],
        [r"\d\s*\.\s*Giá\s+bán",
         r"2\s*\.\s*Giá\s+bán\s+xăng\s+dầu",
         r"Bộ\s+Công\s+Thương\s+thông\s+báo", 
         r"Nơi\s+nhận",
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
    if "ở mức 0 đồng/lít" in contrib_block.lower() or "mức 0 đồng" in contrib_block.lower():
        for code in ["DIESEL", "MAZUT", "RON95_III"]:
            if code not in contrib_map:
                contrib_map[code] = "0"
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
        append_log(f"PARSE v24 SKIP: html not found for doc_id={doc_id}")
        return []

    html = html_path.read_text(encoding="utf-8", errors="ignore")

    soup, text, tables = extract_main_content(html)
    event_date_raw = parse_event_date(soup, text)

    base_map: dict[str, dict] = {}
    
    # VCB exchange rate
    vcb_rate_raw: Optional[str] = None
    for tbl in tables:
        if is_vcb_table(tbl):
            vcb_rate_raw = extract_vcb_rate(tbl)
            if vcb_rate_raw:
                break
    vcb_rate = parse_number(vcb_rate_raw)

    for tbl in tables:
        if is_price_table(tbl):
            base_map = extract_base_prices_from_table(tbl, doc_id=doc_id)
            if base_map:
                break

    retail_map = extract_retail_from_text(text)
    contribution_map, spending_map = parse_bog_sections(text)

    # FIX-A: Context-aware remap RON95 → RON95_III and E5 → E5RON92 (Bảo vệ pre-2018 bằng Guard)
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
        if not retail_price_raw and base_price_raw:
            # Nếu text không có giá lẻ nhưng bảng cơ sở có giá, lấy luôn giá bảng làm giá lẻ (đặc trưng công văn đầu 2018)
            retail_price_raw = base_price_raw
            retail_price = base_price
            extraction_method = "table"
        bog_contribution_raw: Optional[BogRawValue] = contribution_map.get(fuel_code)
        bog_spending_raw:     Optional[BogRawValue] = spending_map.get(fuel_code)
        if bog_contribution_raw and (bog_spending_raw is None or bog_spending_raw == ""):bog_spending_raw = "0"
    
        if bog_spending_raw and (bog_contribution_raw is None or bog_contribution_raw == ""):bog_contribution_raw = "0"

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
            ("vcb_rate_raw",         vcb_rate_raw),
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
            "vcb_rate_raw":          vcb_rate_raw,
            "vcb_rate":              vcb_rate,
            "unit_raw":              unit_raw,
            "extraction_method":     extraction_method,
            "parse_status":          "parsed_ok" if not missing else "parsed_partial",
            "missing_fields":        ";".join(missing),
        })

    return rows




# ═══════════════════════════════════════════════════════════════════════════════
# Extra output — Pure VCB sell-rate extraction
# Xuất thêm: data/interim/vcb_sell_rates_all.csv
# ═══════════════════════════════════════════════════════════════════════════════

def extract_pure_vcb_sell_column(table_tag: Tag) -> list[tuple[str, str]]:
    """
    Xây dựng lưới bảng độc lập, bốc trực tiếp text node từ BeautifulSoup
    để chống lỗi tự động sửa chữ (repair_cell) của parser chính.

    Output mỗi record: (date_str, vcb_sell_price_raw)
    """
    grid: dict[tuple[int, int], str] = {}
    row_idx = 0

    # 1. Tự dựng grid thô, không gọi repair_cell/parse_number.
    for tr in table_tag.find_all("tr"):
        if tr.find_parent("table") is not table_tag:
            continue

        col_idx = 0
        for cell in tr.find_all(["td", "th"], recursive=False):
            while (row_idx, col_idx) in grid:
                col_idx += 1

            raw_text = cell.get_text(" ", strip=True)

            try:
                rowspan = max(1, int(cell.get("rowspan", 1)))
                colspan = max(1, int(cell.get("colspan", 1)))
            except (ValueError, TypeError):
                rowspan = colspan = 1

            for r in range(row_idx, row_idx + rowspan):
                for c in range(col_idx, col_idx + colspan):
                    grid[(r, c)] = raw_text

            col_idx += colspan
        row_idx += 1

    if not grid:
        return []

    max_r = max(r for r, c in grid) + 1
    max_c = max(c for r, c in grid) + 1
    matrix = [[grid.get((r, c), "") for c in range(max_c)] for r in range(max_r)]

    # 2. Định vị cột VCB bán.
    vcb_ban_col: Optional[int] = None
    n_header = 0

    for r, row in enumerate(matrix[:5]):
        for c, cell in enumerate(row):
            txt = re.sub(r"\s+", "", no_accent(cell))
            if "ban" not in txt:
                continue
            vcb_ban_col = c
            n_header = r + 1
            break
        if vcb_ban_col is not None:
            break

    if vcb_ban_col is None:
        return []

    extracted_records: list[tuple[str, str]] = []
    data_rows = matrix[n_header:]

    # 3. Quét dòng và lấy nguyên trạng chuỗi ký tự.
    for row in data_rows:
        if len(row) <= vcb_ban_col:
            continue

        first_cell = no_accent(row[0]) if len(row) > 0 else ""
        second_cell = no_accent(row[1]) if len(row) > 1 else ""
        combined_check = first_cell + " " + second_cell

        # File này cần từng dòng tỷ giá ngày, nên bỏ dòng tổng/trung bình.
        if any(kw in combined_check for kw in ["trung", "tb", "bquan", "bq", "quan", "average", "tong"]):
            continue

        date_match: Optional[str] = None
        for cell in row[:3]:
            m_date = re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", cell)
            if m_date:
                date_match = m_date.group()
                break

        if date_match:
            price_raw = row[vcb_ban_col].strip()
            extracted_records.append((date_match, price_raw))

    return extracted_records


def parse_vcb_rates_pipeline() -> None:
    """
    Parser phụ để xuất riêng cột tỷ giá bán VCB thô.

    Hàm này độc lập với incremental parser chính:
    - Không đụng parse_status trong registry.
    - Không phụ thuộc việc parsed_documents.csv có doc mới hay không.
    - Luôn ghi vcb_sell_rates_all.csv, kể cả khi không có dòng nào.
    """
    ensure_directories()
    append_log("VCB PURE PARSER: Khởi chạy bộ quét thô cô lập...")

    registry = safe_read_csv(DOCUMENT_REGISTRY_FILE)
    columns = ["doc_id", "date", "vcb_sell_price_raw"]

    if registry.empty:
        INTERIM_DIR.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=columns).to_csv(VCB_OUTPUT_FILE, index=False, encoding="utf-8-sig")
        append_log(f"VCB PURE PARSER: registry empty → created empty file: {VCB_OUTPUT_FILE}")
        return

    vcb_all_rows: list[dict] = []
    docs_scanned = 0
    docs_after_date_filter = 0
    docs_with_vcb_table = 0
    docs_with_records = 0

    for _, row in registry.iterrows():
        doc_id = one_line(str(row.get("doc_id", "")))
        if not doc_id:
            continue

        html_path = RAW_DOCUMENTS_DIR / f"{doc_id}.html"
        if not html_path.exists():
            continue

        docs_scanned += 1

        try:
            html_content = html_path.read_text(encoding="utf-8", errors="ignore")
            soup, text, tables = extract_main_content(html_content)

            # Bộ lọc thời gian: chỉ lấy từ tháng 05/2018 trở đi.
            event_date_raw = parse_event_date(soup, text)
            event_dt = pd.to_datetime(event_date_raw, format="%d/%m/%Y", errors="coerce")
            if pd.isna(event_dt) or event_dt < pd.Timestamp("2018-05-01"):
                continue
            docs_after_date_filter += 1

            for tbl in tables:
                if is_vcb_table(tbl):
                    docs_with_vcb_table += 1
                    records = extract_pure_vcb_sell_column(tbl)
                    for date_str, price_raw in records:
                        vcb_all_rows.append({
                            "doc_id": doc_id,
                            "date": date_str,
                            "vcb_sell_price_raw": str(price_raw),
                        })
                    if records:
                        docs_with_records += 1
                        break

        except Exception as e:
            append_log(f"VCB PURE PARSER ERROR: doc_id={doc_id} | {e}")

    output_df = pd.DataFrame(vcb_all_rows, columns=columns)
    if "vcb_sell_price_raw" in output_df.columns:
        output_df["vcb_sell_price_raw"] = output_df["vcb_sell_price_raw"].astype(str)

    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    output_df.to_csv(VCB_OUTPUT_FILE, index=False, encoding="utf-8-sig")

    append_log(
        f"VCB PURE PARSER DONE: docs_scanned={docs_scanned}, "
        f"docs_after_date_filter={docs_after_date_filter}, "
        f"docs_with_vcb_table={docs_with_vcb_table}, "
        f"docs_with_records={docs_with_records}, rows={len(output_df)}"
    )
    append_log(f"VCB PURE PARSER OUTPUT: {VCB_OUTPUT_FILE}")


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

def _empty_output_row(doc_id: str, parse_status: str, note: str = "") -> dict:
    """Tạo một dòng đúng schema mới cho doc không parse được/no_table/error."""
    return {
        "doc_id": doc_id,
        "event_date_raw": None,
        "fuel_type_raw": None,
        "fuel_code_candidate": None,
        "base_price_raw": None,
        "base_price": None,
        "retail_price_raw": None,
        "retail_price": None,
        "bog_contribution_raw": None,
        "bog_spending_raw": None,
        "vcb_rate_raw": None,
        "vcb_rate": None,
        "unit_raw": None,
        "extraction_method": None,
        "parse_status": parse_status,
        "missing_fields": note,
    }


def parse_document_content():
    """
    Entry point tương thích pipeline cũ:
    - Vẫn đọc DOCUMENT_REGISTRY_FILE.
    - Vẫn chỉ parse các doc có crawl_status == "fetched".
    - Vẫn bỏ qua doc_id đã xuất hiện trong OUTPUT_FILE.
    - Vẫn ghi ra đúng PARSED_DOCUMENTS_FILE để run_pipeline.bat không hư.
    - Vẫn cập nhật parse_status trong document_registry.csv.

    Khác file cũ:
    - Schema output giữ theo parser mới, không ép về các cột cũ.
    """
    ensure_directories()
    append_log("PARSE v24 COMPAT: start")

    registry = safe_read_csv(DOCUMENT_REGISTRY_FILE)
    if registry.empty:
        append_log("PARSE v24 COMPAT: registry empty → skip")
        parse_vcb_rates_pipeline()
        return
    if "doc_id" not in registry.columns:
        append_log("PARSE v24 COMPAT ERROR: missing doc_id column")
        parse_vcb_rates_pipeline()
        return

    if "crawl_status" not in registry.columns:
        registry["crawl_status"] = ""
    if "parse_status" not in registry.columns:
        registry["parse_status"] = "not_parsed"

    existing_df = safe_read_csv(OUTPUT_FILE)
    if existing_df.empty:
        existing_df = pd.DataFrame(columns=PARSED_COLUMNS)
        already_parsed: set[str] = set()
    else:
        # Bảo vệ trường hợp file csv cũ thiếu một vài cột mới.
        for col in PARSED_COLUMNS:
            if col not in existing_df.columns:
                existing_df[col] = None
        existing_df = existing_df[PARSED_COLUMNS]
        already_parsed = set(existing_df["doc_id"].dropna().astype(str).tolist())

    to_parse = registry[
        (registry["crawl_status"].astype(str) == "fetched")
        & (~registry["doc_id"].astype(str).isin(already_parsed))
    ].copy()

    append_log(
        f"PARSE v24 COMPAT: {len(to_parse)} docs cần parse, "
        f"{len(already_parsed)} doc_id đã có trong output"
    )

    new_rows: list[dict] = []
    stats = {"ok": 0, "partial": 0, "no_table": 0, "error": 0, "missing_html": 0}

    for _, row in to_parse.iterrows():
        doc_id = one_line(str(row.get("doc_id", "")))
        if not doc_id:
            stats["error"] += 1
            continue

        html_path = RAW_DOCUMENTS_DIR / f"{doc_id}.html"
        if not html_path.exists():
            # Giống tinh thần code cũ: ghi nhận lỗi để không im lặng mất doc.
            new_rows.append(_empty_output_row(doc_id, "parse_error", f"html not found: {html_path}"))
            stats["missing_html"] += 1
            append_log(f"PARSE v24 COMPAT MISSING_HTML: doc_id={doc_id}")
            continue

        try:
            parsed = parse_one_document(row)
            if parsed:
                # Bảo đảm mọi row đúng schema mới, không lẫn cột ngoài ý muốn.
                for rec in parsed:
                    normalized = {col: rec.get(col) for col in PARSED_COLUMNS}
                    new_rows.append(normalized)

                if any(r.get("parse_status") == "parsed_ok" for r in parsed):
                    stats["ok"] += 1
                else:
                    stats["partial"] += 1
                append_log(f"PARSE v24 COMPAT OK: {doc_id} → {len(parsed)} rows")
            else:
                new_rows.append(_empty_output_row(doc_id, "no_table", "no parsed fuel rows"))
                stats["no_table"] += 1
                append_log(f"PARSE v24 COMPAT NO_TABLE: doc_id={doc_id}")

        except Exception as e:
            new_rows.append(_empty_output_row(doc_id, "parse_error", str(e)[:300]))
            stats["error"] += 1
            append_log(f"PARSE v24 COMPAT ERROR: doc_id={doc_id} | {e}")

    if not new_rows:
        append_log("PARSE v24 COMPAT DONE: không có gì mới")
        parse_vcb_rates_pipeline()
        return

    new_df = pd.DataFrame(new_rows, columns=PARSED_COLUMNS)
    combined = pd.concat([existing_df, new_df], ignore_index=True)
    combined = combined[PARSED_COLUMNS]

    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    try:
        combined.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    except PermissionError:
        fb = OUTPUT_FILE.with_name(OUTPUT_FILE.stem + "_new.csv")
        combined.to_csv(fb, index=False, encoding="utf-8-sig")
        append_log(f"PARSE v24 COMPAT WARNING: output locked → {fb}")

    # Cập nhật parse_status trong registry giống code cũ.
    ok_ids = set(
        new_df.loc[new_df["parse_status"].isin(["parsed_ok", "parsed_partial"]), "doc_id"]
        .dropna().astype(str).tolist()
    )
    no_table_ids = set(
        new_df.loc[new_df["parse_status"].astype(str) == "no_table", "doc_id"]
        .dropna().astype(str).tolist()
    )
    error_ids = set(
        new_df.loc[new_df["parse_status"].astype(str) == "parse_error", "doc_id"]
        .dropna().astype(str).tolist()
    )

    registry.loc[registry["doc_id"].astype(str).isin(ok_ids), "parse_status"] = "parsed"
    registry.loc[registry["doc_id"].astype(str).isin(no_table_ids), "parse_status"] = "no_table"
    registry.loc[registry["doc_id"].astype(str).isin(error_ids), "parse_status"] = "parse_error"
    registry.to_csv(DOCUMENT_REGISTRY_FILE, index=False, encoding="utf-8-sig")

    n_ok = (combined["parse_status"] == "parsed_ok").sum()
    n_partial = (combined["parse_status"] == "parsed_partial").sum()
    n_table = combined["extraction_method"].astype(str).str.contains("table", na=False).sum()
    n_text = (combined["extraction_method"].astype(str) == "text").sum()

    append_log(
        f"PARSE v24 COMPAT DONE: new_rows={len(new_df)}, total_rows={len(combined)}, "
        f"ok_docs={stats['ok']}, partial_docs={stats['partial']}, "
        f"no_table={stats['no_table']}, error={stats['error']}, "
        f"missing_html={stats['missing_html']}"
    )
    append_log(f"PARSE v24 COMPAT METHOD: table_rows={n_table}, text_only={n_text}")
    append_log(f"PARSE v24 COMPAT OUTPUT: {OUTPUT_FILE}")

    # Xuất thêm file tỷ giá bán VCB thô trong cùng bước parse.
    parse_vcb_rates_pipeline()


if __name__ == "__main__":
    parse_document_content()
