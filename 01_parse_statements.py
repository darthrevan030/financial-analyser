"""
Bank Statement Parser — DBS (Consolidated) + Standard Chartered
Run this first to extract all transactions into a single CSV.

Usage:
    python 01_parse_statements.py

Place your PDFs in a folder called 'statements/' next to this script.
Output: transactions.csv
"""

import pdfplumber
import pandas as pd
import re
import os
from pathlib import Path
from datetime import datetime

# ─── CONFIG ──────────────────────────────────────────────────────────────────

STATEMENTS_DIR = Path("S:/MISC/Bank Statements")   # folder containing your PDFs
OUTPUT_CSV     = Path("transactions.csv")

# ─── DBS CONSOLIDATED STATEMENT PARSER ───────────────────────────────────────
#
# DBS consolidated statements list multiple accounts (Multiplier, MySavings,
# Cashline, Credit Card, etc.) in sections. Each section has a header like:
#   "DBS Multiplier Account  Account No: XXX-XXXXX-X"
# followed by a transaction table with columns:
#   Date | Transaction Details | Withdrawal | Deposit | Balance
#
# Credit card sections use:
#   Date | Description | Amount (DR/CR suffix or sign)

DBS_ACCOUNT_HEADER = re.compile(
    r"(DBS\s[\w\s]+Account|DBS\s[\w\s]+Card|Cashline|Autosave|eMySavings)",
    re.IGNORECASE
)

DBS_ACCT_NO = re.compile(r"Account\s*No[.:]?\s*([\d\-]+)", re.IGNORECASE)

# Transaction date patterns DBS uses: "15 Jan 2024" or "15/01/2024"
DBS_DATE = re.compile(r"(\d{1,2}\s+[A-Za-z]{3}\s+\d{4}|\d{2}/\d{2}/\d{4})")

# Amount: digits with commas and decimals, optional CR/DR
AMOUNT_RE = re.compile(r"([\d,]+\.\d{2})\s*(CR|DR)?", re.IGNORECASE)


def parse_amount(raw: str) -> float | None:
    """Convert '1,234.56 CR' → +1234.56, '1,234.56 DR' → -1234.56"""
    if not raw:
        return None
    raw = raw.strip()
    m = AMOUNT_RE.search(raw)
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    suffix = (m.group(2) or "").upper()
    if suffix == "DR":
        val = -val
    return val


def parse_date(raw: str) -> str | None:
    """Normalise various date formats to YYYY-MM-DD."""
    raw = raw.strip()
    for fmt in ("%d %b %Y", "%d/%m/%Y", "%d-%b-%Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_dbs(pdf_path: Path) -> list[dict]:
    """
    Parse a DBS consolidated statement PDF.
    Returns a list of transaction dicts.
    """
    transactions = []
    current_account = "DBS Unknown"
    current_acct_no = ""

    with pdfplumber.open(pdf_path) as pdf:
        statement_year = None

        for page in pdf.pages:
            text = page.extract_text() or ""

            # Try to detect statement period year from header
            year_match = re.search(r"Statement\s+Period.*?(\d{4})", text)
            if year_match:
                statement_year = year_match.group(1)

            # Detect account section changes
            for line in text.splitlines():
                acct_match = DBS_ACCOUNT_HEADER.search(line)
                if acct_match:
                    current_account = acct_match.group(0).strip()
                    no_match = DBS_ACCT_NO.search(line)
                    current_acct_no = no_match.group(1) if no_match else ""

            # ── Table extraction ──────────────────────────────────────────
            tables = page.extract_tables({
                "vertical_strategy":   "lines",
                "horizontal_strategy": "lines",
            })

            for table in tables:
                if not table or len(table) < 2:
                    continue

                # Detect column structure from header row
                header = [str(c).strip().lower() if c else "" for c in table[0]]
                has_withdrawal = any("withdrawal" in h or "debit" in h for h in header)
                has_deposit    = any("deposit"    in h or "credit" in h for h in header)
                has_amount     = any("amount" in h for h in header)

                date_col    = next((i for i, h in enumerate(header) if "date"   in h), 0)
                desc_col    = next((i for i, h in enumerate(header) if "desc"   in h or "detail" in h or "transaction" in h), 1)
                debit_col   = next((i for i, h in enumerate(header) if "withdrawal" in h or "debit"  in h), None)
                credit_col  = next((i for i, h in enumerate(header) if "deposit"    in h or "credit" in h), None)
                amount_col  = next((i for i, h in enumerate(header) if "amount" in h), None)

                for row in table[1:]:
                    if not row or all(c is None or str(c).strip() == "" for c in row):
                        continue

                    raw_date = str(row[date_col] or "").strip()
                    if not DBS_DATE.search(raw_date):
                        continue   # skip non-transaction rows

                    date_str = parse_date(DBS_DATE.search(raw_date).group(0))
                    if not date_str:
                        continue

                    description = str(row[desc_col] or "").strip().replace("\n", " ")

                    # Determine amount & direction
                    amount = None
                    txn_type = ""

                    if has_withdrawal and has_deposit:
                        debit_raw  = str(row[debit_col]  or "") if debit_col  is not None else ""
                        credit_raw = str(row[credit_col] or "") if credit_col is not None else ""
                        if debit_raw.strip():
                            amount   = -(parse_amount(debit_raw) or 0)
                            txn_type = "debit"
                        elif credit_raw.strip():
                            amount   = parse_amount(credit_raw) or 0
                            txn_type = "credit"
                    elif amount_col is not None:
                        raw_amt = str(row[amount_col] or "")
                        amount  = parse_amount(raw_amt)
                        txn_type = "credit" if (amount or 0) >= 0 else "debit"

                    if amount is None:
                        continue

                    transactions.append({
                        "date":        date_str,
                        "bank":        "DBS",
                        "account":     current_account,
                        "account_no":  f"****{current_acct_no[-4:]}" if current_acct_no else "",
                        "description": description,
                        "amount":      round(amount, 2),
                        "type":        txn_type,
                        "source_file": pdf_path.name,
                    })

    return transactions


# ─── STANDARD CHARTERED PARSER ───────────────────────────────────────────────
#
# SCB statements are per-account PDFs. Layout:
#   Date | Description | Withdrawals | Deposits | Balance
# Credit card variant:
#   Transaction Date | Posting Date | Description | Amount

SCB_DATE = re.compile(r"(\d{2}\s+[A-Za-z]{3}\s+\d{4}|\d{2}/\d{2}/\d{4}|\d{2}\s+[A-Za-z]{3})")


def parse_scb(pdf_path: Path) -> list[dict]:
    """
    Parse a Standard Chartered statement PDF.
    Returns a list of transaction dicts.
    """
    transactions = []
    account_type = "SCB Account"
    acct_no_raw  = ""

    with pdfplumber.open(pdf_path) as pdf:
        # Grab account info from first page
        first_text = pdf.pages[0].extract_text() or ""
        acct_match = re.search(r"Account\s*(?:No|Number)[.:]?\s*([\d\-X*]+)", first_text, re.I)
        if acct_match:
            acct_no_raw = acct_match.group(1)
        type_match = re.search(r"(BonusSaver|e\$aver|JumpStart|Salary|\bSavings\b|\bCurrent\b|EasyCredit|Platinum|Unlimited|Simply Cash)", first_text, re.I)
        if type_match:
            account_type = f"SCB {type_match.group(0).strip()}"

        # Detect statement year for short dates like "15 Jan"
        year_match = re.search(r"Statement\s+(?:Date|Period).*?(\d{4})", first_text)
        statement_year = year_match.group(1) if year_match else str(datetime.now().year)

        for page in pdf.pages:
            tables = page.extract_tables({
                "vertical_strategy":   "lines",
                "horizontal_strategy": "lines",
            })

            for table in tables:
                if not table or len(table) < 2:
                    continue

                header = [str(c).strip().lower() if c else "" for c in table[0]]

                date_col   = next((i for i, h in enumerate(header) if "date" in h and "post" not in h), 0)
                desc_col   = next((i for i, h in enumerate(header) if "desc" in h or "particular" in h or "detail" in h or "narration" in h), 1)
                debit_col  = next((i for i, h in enumerate(header) if "withdrawal" in h or "debit" in h), None)
                credit_col = next((i for i, h in enumerate(header) if "deposit" in h or "credit" in h), None)
                amount_col = next((i for i, h in enumerate(header) if "amount" in h), None)

                for row in table[1:]:
                    if not row or all(c is None or str(c).strip() == "" for c in row):
                        continue

                    raw_date = str(row[date_col] or "").strip()
                    date_m   = SCB_DATE.search(raw_date)
                    if not date_m:
                        continue

                    raw_date_str = date_m.group(0)
                    # Handle short dates like "15 Jan" — append statement year
                    if re.match(r"\d{2}\s+[A-Za-z]{3}$", raw_date_str):
                        raw_date_str = f"{raw_date_str} {statement_year}"

                    date_str = parse_date(raw_date_str)
                    if not date_str:
                        continue

                    description = str(row[desc_col] or "").strip().replace("\n", " ")

                    amount   = None
                    txn_type = ""

                    if debit_col is not None and credit_col is not None:
                        debit_raw  = str(row[debit_col]  or "").strip()
                        credit_raw = str(row[credit_col] or "").strip()
                        if debit_raw:
                            amount   = -(parse_amount(debit_raw) or 0)
                            txn_type = "debit"
                        elif credit_raw:
                            amount   = parse_amount(credit_raw) or 0
                            txn_type = "credit"
                    elif amount_col is not None:
                        raw_amt  = str(row[amount_col] or "")
                        amount   = parse_amount(raw_amt)
                        txn_type = "credit" if (amount or 0) >= 0 else "debit"

                    if amount is None:
                        continue

                    transactions.append({
                        "date":        date_str,
                        "bank":        "Standard Chartered",
                        "account":     account_type,
                        "account_no":  f"****{acct_no_raw[-4:]}" if acct_no_raw else "",
                        "description": description,
                        "amount":      round(amount, 2),
                        "type":        txn_type,
                        "source_file": pdf_path.name,
                    })

    return transactions


# ─── BANK DETECTOR ───────────────────────────────────────────────────────────

def detect_bank(pdf_path: Path) -> str:
    """Quick scan of first page text to detect bank."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = (pdf.pages[0].extract_text() or "").lower()
            if "dbs" in text or "posb" in text:
                return "DBS"
            if "standard chartered" in text or "stanchart" in text:
                return "SCB"
    except Exception:
        pass
    return "UNKNOWN"


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    if not STATEMENTS_DIR.exists():
        print(f"❌  Folder '{STATEMENTS_DIR}' not found.")
        print(f"    Create it and place your PDF statements inside, then re-run.")
        return

    pdfs = sorted(STATEMENTS_DIR.glob("**/*.pdf"))
    if not pdfs:
        print(f"❌  No PDF files found in '{STATEMENTS_DIR}/'")
        return

    all_transactions = []
    errors = []

    for pdf_path in pdfs:
        bank = detect_bank(pdf_path)
        print(f"  Processing [{bank:>18}]  {pdf_path.name} ...", end="", flush=True)
        try:
            if bank == "DBS":
                txns = parse_dbs(pdf_path)
            elif bank == "SCB":
                txns = parse_scb(pdf_path)
            else:
                print(f"  ⚠️  Unrecognised bank — skipping")
                errors.append(pdf_path.name)
                continue
            all_transactions.extend(txns)
            print(f"  ✓  {len(txns):>4} transactions")
        except Exception as e:
            print(f"  ✗  ERROR: {e}")
            errors.append(pdf_path.name)

    if not all_transactions:
        print("\n⚠️  No transactions extracted. Check your PDF layout matches expected format.")
        print("    Run  02_debug_pdf.py  on a sample file to inspect raw table output.")
        return

    df = pd.DataFrame(all_transactions)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    # Remove duplicates (same date + description + amount across overlapping statements)
    before = len(df)
    df = df.drop_duplicates(subset=["date", "description", "amount", "account"])
    dupes = before - len(df)

    df.to_csv(OUTPUT_CSV, index=False)

    print(f"\n{'─'*55}")
    print(f"  ✅  Done!")
    print(f"      Total transactions : {len(df):,}")
    print(f"      Duplicates removed : {dupes:,}")
    print(f"      Date range         : {df['date'].min().date()} → {df['date'].max().date()}")
    print(f"      Output             : {OUTPUT_CSV}")
    print(f"{'─'*55}")
    if errors:
        print(f"\n  ⚠️  Files skipped: {', '.join(errors)}")
    print(f"\n  Next step: run  02_categorise.py")


if __name__ == "__main__":
    main()
