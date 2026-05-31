# Vietnam Fuel Price Dataset (2016–2026)

A benchmark dataset of Vietnam's retail fuel price regulatory decisions, built from official government documents published by the Ministry of Industry and Trade (MOIT).

**307 regulatory events · 10 years · 4 fuel types · fully reproducible pipeline**

---

## Table of Contents

- [Overview](#overview)
- [Dataset Structure](#dataset-structure)
- [Pipeline Architecture](#pipeline-architecture)
- [How to Run](#how-to-run)
- [Data Dictionary](#data-dictionary)
- [Coverage Analysis](#coverage-analysis)
- [Known Limitations](#known-limitations)
- [Citation](#citation)

---

## Overview

In Vietnam, retail fuel prices are regulated by the Ministry of Industry and Trade (MOIT) on a rolling basis — typically every 7 days per Decree 83/2014/NĐ-CP, with earlier adjustments permitted during high volatility. Each regulatory cycle publishes:

- Retail price ceilings for each fuel type
- Base price (giá cơ sở) calculations
- Price Stabilization Fund (Quỹ Bình ổn Giá — BOG) contribution and spending levels
- World market reference prices and USD/VND exchange rates

No machine-readable historical dataset of this data existed prior to this project. This pipeline constructs one from scratch using official legal documents archived at [Thư Viện Pháp Luật (TVPL)](https://thuvienphapluat.vn).

---

## Dataset Structure

```
data/
├── raw/
│   ├── registry/
│   │   └── document_registry.csv      # Metadata of all discovered documents
│   └── documents/
│       └── *.html                     # Raw HTML of each regulatory document
│
├── interim/
│   ├── parsed_event_prices_raw.csv    # Parsed prices per document per fuel type
│   └── document_completeness.csv     # Parse quality flags
│
└── processed/
    ├── event_features.csv             # One row per regulatory event (wide format)
    ├── daily_panel.csv                # One row per calendar day (forward-filled)
    └── dataset_manifest.csv          # Version history and update log
```

### Key files

| File | Rows | Description |
|------|------|-------------|
| `document_registry.csv` | 308 | Document metadata, fetch and parse status |
| `parsed_event_prices_raw.csv` | 1,222 | Raw parsed prices (long format: one row per document × fuel type) |
| `event_features.csv` | ~307 | Clean event-level dataset (wide format, one row per regulatory cycle) |
| `daily_panel.csv` | ~3,650 | Daily time series with forward-filled prices, external features |

---

## Pipeline Architecture

```
TVPL Website
     │
     ▼
[1] discover_documents.py   →  document_registry.csv
     │
     ▼
[2] fetch_document_html.py  →  data/raw/documents/*.html
     │
     ▼
[3] parse_document_content.py  →  parsed_event_prices_raw.csv
     │
     ▼
[4] build_event_dataset.py  →  event_features.csv
     │
     ▼
[5] build_daily_dataset.py  →  daily_panel.csv
     │
     ▼
[6] run_update.py           →  incremental update (new documents only)
```

**Design principles:**

- **Separation of concerns:** Discover, Fetch, and Parse are independent stages. Fetch failures can be retried without re-crawling the registry.
- **Raw artifact preservation:** Full HTML is stored before parsing. Logic changes do not require re-fetching.
- **Incremental updates:** `run_update.py` only processes documents not yet in the registry — full re-crawl is never needed.
- **Reproducibility:** No manual data manipulation. Every transformation is code.

---

## How to Run

### Requirements

```bash
pip install -r requirements.txt
```

Requires Python 3.10+. Selenium requires ChromeDriver matching your Chrome version.

### Full pipeline (first run)

```bash
# Step 1: Discover documents
python src/discover_documents.py

# Step 2: Fetch HTML
python src/fetch_document_html.py

# Step 3: Parse content
python src/parse_document_content.py

# Step 4: Build event dataset
python src/build_event_dataset.py

# Step 5: Build daily panel
python src/build_daily_dataset.py
```

### Incremental update (subsequent runs)

```bash
python src/run_update.py
```

This will: discover new documents → fetch only new ones → parse → append to existing datasets → log the update in `dataset_manifest.csv`.

---

## Data Dictionary

### `event_features.csv`

| Column | Type | Description |
|--------|------|-------------|
| `event_date` | date | Date the new prices take effect |
| `doc_number` | string | Official document number (e.g. `1273/BCT-TTTN`) |
| `prev_event_date` | date | Previous regulatory event date |
| `gasoline_standard_retail` | float | Retail price — GASOLINE_STANDARD (VND/liter) |
| `ron95_retail` | float | Retail price — RON95-III (VND/liter) |
| `diesel_retail` | float | Retail price — Diesel DO 0.05S (VND/liter) |
| `mazut_retail` | float | Retail price — Mazut FO 180CST (VND/kg) |
| `gasoline_standard_base` | float | Base price — GASOLINE_STANDARD (VND/liter) |
| `ron95_base` | float | Base price — RON95-III (VND/liter) |
| `bog_contribution_*` | float | BOG contribution level per fuel type (VND/liter) |
| `bog_spending_*` | float | BOG spending level per fuel type (VND/liter) |
| `usd_vnd` | float | USD/VND sell rate, Vietcombank (as-of join) |
| `is_event_day` | int | 1 = regulatory event day |

**Note on GASOLINE_STANDARD:** This column concatenates RON92 (Jan 2016 – Dec 2017) and E5 RON92 (Jan 2018 – present) into a single continuous series. Pearson correlation between the two series during their overlap period: r = 0.9959. See Section 3.3 of the technical report for full justification.

### `daily_panel.csv`

All columns from `event_features.csv` plus:

| Column | Type | Description |
|--------|------|-------------|
| `date` | date | Calendar date |
| `brent_usd` | float | Brent crude oil price (USD/barrel) |
| `wti_usd` | float | WTI crude oil price (USD/barrel) |
| `delta_brent` | float | Day-over-day change in Brent price |
| `delta_wti` | float | Day-over-day change in WTI price |
| `delta_fx` | float | Day-over-day change in USD/VND rate |
| `brent_mean_3d` | float | 3-day rolling mean of Brent |
| `brent_std_3d` | float | 3-day rolling std of Brent |
| `days_since_last_event` | int | Days since previous regulatory cycle |
| `month_sin` / `month_cos` | float | Cyclical encoding of month |
| `dow_sin` / `dow_cos` | float | Cyclical encoding of day of week |

---

## Coverage Analysis

| Metric | Value |
|--------|-------|
| TVPL documents collected | 294 |
| MOIT reference documents | 311 |
| Matched by event date | 240 |
| TVPL-only | 54 |
| MOIT-only (raw) | 63 |

**Root cause analysis of 63 MOIT-only records:**

| Category | Count | Note |
|----------|-------|------|
| Before 2016 (out of scope) | 37 | Outside study period |
| Administrative documents (non-price) | 5 | Mis-indexed by MOIT as pricing documents |
| Recent documents not yet on TVPL (2024–2026) | 12 | Indexing lag |
| TVPL not yet indexed (2016–2023) | 14 | Genuine coverage gap |

After adjusting for out-of-scope and non-price documents, **14 genuine gaps** remain in the 2016–2023 period. Effective coverage: **≥ 95%** of all regulatory events within scope.

---

## Known Limitations

- **Source dependency:** Pipeline depends on TVPL's HTML structure. Layout changes may require parser updates.
- **BOG sentinel values:** Some documents use text phrases ("giữ nguyên mức trích lập") instead of numeric values. These are resolved via carry-forward logic in `build_event_dataset.py`.
- **Parsed partial records:** 72 rows (5.9%) are flagged `parsed_partial`, primarily due to missing BOG tables in 2024–2026 documents. Retail prices are intact for 98.9% of all rows.
- **External data dependency:** `daily_panel.csv` requires external Brent/WTI prices and VCB exchange rates. See `data/external/` for required format specifications.
- **No real-time update guarantee:** TVPL indexing lag means documents from the last 30–60 days may not yet be available.

---

## Citation

If you use this dataset in research or coursework, please cite:

```
@dataset{vietnam_fuel_price_2026,
  title     = {Vietnam Retail Fuel Price Dataset 2016--2026},
  author    = {[Your Name]},
  year      = {2026},
  publisher = {Kaggle Datasets},
  url       = {https://kaggle.com/datasets/...}
}
```

---

## License

Data sourced from official Vietnamese government documents (public domain). Code is released under MIT License.
