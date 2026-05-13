"""
PDF Debug Helper
Use this if 01_parse_statements.py extracts 0 transactions from a file.
It prints the raw table content pdfplumber sees, so you can understand
the layout and adjust the parsers accordingly.

Usage:
    python 00_debug_pdf.py path/to/statement.pdf
"""

import sys
import pdfplumber
from pathlib import Path


def debug(pdf_path: Path, max_pages: int = 5):
    print(f"\n{'═'*60}")
    print(f"  FILE: {pdf_path.name}")
    print(f"{'═'*60}")

    with pdfplumber.open(pdf_path) as pdf:
        print(f"  Total pages: {len(pdf.pages)}")
        print(f"  Inspecting first {min(max_pages, len(pdf.pages))} pages...\n")

        for i, page in enumerate(pdf.pages[:max_pages]):
            print(f"\n{'─'*60}")
            print(f"  PAGE {i+1}")
            print(f"{'─'*60}")

            # Raw text
            text = page.extract_text() or "(no text)"
            lines = text.splitlines()
            print(f"\n  [RAW TEXT — first 30 lines]")
            for line in lines[:30]:
                print(f"    {repr(line)}")
            if len(lines) > 30:
                print(f"    ... ({len(lines) - 30} more lines)")

            # Tables (default strategy)
            print(f"\n  [TABLES — lines strategy]")
            tables_lines = page.extract_tables({
                "vertical_strategy":   "lines",
                "horizontal_strategy": "lines",
            })
            if not tables_lines:
                print("    (none found)")
            for j, table in enumerate(tables_lines):
                print(f"\n    Table {j+1} ({len(table)} rows):")
                for k, row in enumerate(table[:8]):
                    print(f"      Row {k:02}: {row}")
                if len(table) > 8:
                    print(f"      ... ({len(table) - 8} more rows)")

            # Tables (text strategy — fallback for borderless tables)
            print(f"\n  [TABLES — text strategy (borderless fallback)]")
            tables_text = page.extract_tables({
                "vertical_strategy":   "text",
                "horizontal_strategy": "text",
            })
            if not tables_text:
                print("    (none found)")
            for j, table in enumerate(tables_text[:2]):
                print(f"\n    Table {j+1} ({len(table)} rows):")
                for k, row in enumerate(table[:6]):
                    print(f"      Row {k:02}: {row}")

    print(f"\n{'═'*60}")
    print("  DONE. Use the output above to:")
    print("  1. Confirm date/amount/description column positions")
    print("  2. Adjust column index variables in the parser")
    print("  3. Update regex patterns if date formats differ")
    print(f"{'═'*60}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python 00_debug_pdf.py path/to/statement.pdf [max_pages]")
        sys.exit(1)
    path = Path(sys.argv[1])
    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)
    debug(path, pages)
