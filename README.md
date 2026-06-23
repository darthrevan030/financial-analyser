# Financial Analyser

A personal finance pipeline for Singapore bank statements. Parses PDFs from DBS and Standard Chartered, categorises transactions, and generates charts and an interactive dashboard.

## Pipeline

```text
PDF statements  →  01_parse_statements.py  →  transactions.csv
                →  02_categorise.py         →  transactions_categorised.csv
                →  03_analyse.py            →  analysis_report.txt
                                            →  charts/ (6 PNG charts)
                                            →  dashboard.html
```

Run all steps in order:

```bash
python main.py
```

Or run steps individually:

```bash
python 01_parse_statements.py
python 02_categorise.py
python 03_analyse.py
```

## Setup

**Requirements:** Python 3.14+, [uv](https://docs.astral.sh/uv/)

```bash
uv sync
```

**Place your PDFs** in `S:/MISC/Bank Statements/` (configured at the top of `01_parse_statements.py`).

## Supported Banks

| Bank | Statement format | Detection |
| ---- | --------------- | --------- |
| DBS | Consolidated PDF | Filename contains `dbs` or `posb`, or PDF content |
| Standard Chartered | Monthly PDF | ISO date filename (e.g. `20221231.pdf`) |

Both banks support multiple accounts within the same statement file. Duplicate transactions across overlapping statements are automatically deduplicated.

## Outputs

| File | Description |
| ---- | ----------- |
| `transactions.csv` | All parsed transactions |
| `transactions_categorised.csv` | Transactions with `category` and `subcategory` columns |
| `analysis_report.txt` | Plain-text summary: totals, annual breakdown, top merchants, subscriptions |
| `charts/01_monthly_cashflow.png` | Bar chart of monthly income vs expense with net line |
| `charts/02_annual_summary.png` | Annual income/expense grouped bars + savings rate |
| `charts/03_category_breakdown.png` | Donut chart of total spend by category |
| `charts/04_top_merchants.png` | Top 20 merchants/payees by total spend |
| `charts/05_spending_heatmap.png` | Annual spend by category heatmap |
| `charts/06_cumulative_cashflow.png` | Cumulative net cash flow over time |
| `dashboard.html` | Self-contained interactive dashboard (Chart.js) — open in browser |

## Customising Categories

Edit the `RULES` list in [02_categorise.py](02_categorise.py). Each rule is a tuple of `(regex, category, subcategory)` — first match wins, patterns are case-insensitive.

```python
RULES = [
    (r"grab rides|comfortdelgro", "Transport", "Taxi / Ride-hailing"),
    (r"netflix|spotify",          "Subscriptions", "Streaming / Apps"),
    # ...
]
```

After editing, re-run `02_categorise.py` and `03_analyse.py` — no need to re-parse the PDFs.

## Transaction CSV Schema

| Column | Description |
| ------ | ----------- |
| `date` | Transaction date (YYYY-MM-DD) |
| `bank` | `DBS` or `Standard Chartered` |
| `account` | Account name (e.g. `Multiplier`, `SCB JumpStart`) |
| `account_no` | Last 4 digits, masked (`****1234`) |
| `description` | Raw transaction description |
| `amount` | Positive = credit, negative = debit (SGD) |
| `type` | `credit` or `debit` |
| `source_file` | PDF filename the row came from |
| `category` | Assigned by `02_categorise.py` |
| `subcategory` | Assigned by `02_categorise.py` |

## Dependencies

| Package | Purpose |
| ------- | ------- |
| `pymupdf` | PDF text extraction (DBS statements) |
| `pdfplumber` | PDF parsing fallback |
| `pandas` | Data manipulation and CSV I/O |
| `matplotlib` | Static PNG charts |
