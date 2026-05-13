"""
Bank Statement Parser — DBS (Consolidated) + Standard Chartered
Run this first to extract all transactions into a single CSV.

Usage:
    python 01_parse_statements.py

Place your PDFs in a folder called 'statements/' next to this script.
Output: transactions.csv
"""

import fitz  # pymupdf
import pdfplumber
import pandas as pd
import re
import os
from pathlib import Path
from datetime import datetime

# ─── CONFIG ──────────────────────────────────────────────────────────────────

STATEMENTS_DIR = Path("S:/MISC/Bank Statements")   # folder containing your PDFs
OUTPUT_CSV     = Path("transactions.csv")

# ─── SHARED HELPERS ───────────────────────────────────────────────────────────

AMOUNT_RE = re.compile(r"([\d,]+\.\d{2})\s*(CR|DR)?", re.IGNORECASE)

def parse_amount(raw: str) -> float | None:
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
    raw = raw.strip()
    for fmt in ("%d/%m/%Y", "%d %b %Y", "%d-%b-%Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

# ─── DBS CONSOLIDATED STATEMENT PARSER ───────────────────────────────────────
#
# Uses pymupdf (fitz) for text extraction — handles DBS's custom font encoding
# that breaks pdfplumber.
#
# Layout (from actual statements):
#   Page 1: Account Summary
#   Page 2+: Transaction Details per account
#
# Each account section starts with:
#   "<Account Name>"
#   "Account No. XXX-XXXXXX-X"
#   "Date  Description  Withdrawal (-)  Deposit (+)  Balance"
#   "CURRENCY: SINGAPORE DOLLAR"
#   "Balance Brought Forward   SGD X,XXX.XX"
#   <transactions>
#
# Transaction line format (fixed-width-ish, space separated):
#   04/04/2021  Debit Card Transaction MCDONALD'S  5.70  2,516.55
#
# Amounts: withdrawal in col 3, deposit in col 4, balance in col 5
# Multi-line descriptions continue on next line(s) with no date

DBS_TXN_DATE   = re.compile(r"^\s*(\d{2}/\d{2}/\d{4})\s+(.+)")
DBS_ACCT_NAME  = re.compile(
    r"(My Account|Multiplier|MySavings|eMySavings|Autosave|POSB Savings|"
    r"Current Account|Cashline|Visa|Mastercard|Debit Card|Credit Card|"
    r"Pocket Money|MultiCurrency)",
    re.IGNORECASE
)
DBS_ACCT_NO    = re.compile(r"Account\s+No\.?\s+([\d\-]+)", re.IGNORECASE)
# Amounts at end of line: one or two money values (withdrawal/deposit + balance)
DBS_AMOUNTS    = re.compile(r"([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s*$")
DBS_ONE_AMOUNT = re.compile(r"([\d,]+\.\d{2})\s*$")

SKIP_LINES = re.compile(
    r"Balance Brought Forward|CURRENCY:|Transaction Details|"
    r"Date\s+Description|Withdrawal|Deposit|Balance|Page \d|"
    r"Account Summary|DBS Co\.|POSB Biz|SGD Equivalent|"
    r"^\s*SGD\s*[\d,]+\.\d{2}\s*$",
    re.IGNORECASE
)


def parse_dbs(pdf_path: Path) -> list[dict]:
    """
    Parse a DBS consolidated statement PDF using pymupdf.
    Handles DBS's custom font encoding that breaks pdfplumber.
    """
    transactions = []
    current_account = "DBS Account"
    current_acct_no = ""

    doc = fitz.open(str(pdf_path))

    for page in doc:
        lines = page.get_text().splitlines()

        pending_date     = None
        pending_desc     = []
        pending_txn_type = ""

        def flush_pending():
            """Commit the buffered transaction once we have date+desc+amount."""
            nonlocal pending_date, pending_desc, pending_txn_type
            pending_date = None
            pending_desc = []
            pending_txn_type = ""

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            i += 1

            if not line:
                continue

            # ── Account section header detection ─────────────────────────
            acct_m = DBS_ACCT_NAME.search(line)
            if acct_m and len(line) < 60:
                current_account = line.strip()
                # Next non-empty line may be account number
                j = i
                while j < len(lines) and j < i + 3:
                    nxt = lines[j].strip()
                    no_m = DBS_ACCT_NO.search(nxt)
                    if no_m:
                        current_acct_no = no_m.group(1)
                        break
                    j += 1
                continue

            # ── Skip header / footer lines ────────────────────────────────
            if SKIP_LINES.search(line):
                continue

            # ── Try to match a transaction line (starts with DD/MM/YYYY) ──
            date_m = DBS_TXN_DATE.match(line)
            if date_m:
                # Flush any previous pending transaction (shouldn't have
                # an amount yet at this point — that comes after desc lines)
                # Start new pending transaction
                raw_date  = date_m.group(1)
                remainder = date_m.group(2).strip()

                date_str = parse_date(raw_date)
                if not date_str:
                    continue

                # Extract amounts from the remainder if present
                amt_m = DBS_AMOUNTS.search(remainder)
                if amt_m:
                    # Both withdrawal/deposit amount AND balance on same line
                    amt1 = float(amt_m.group(1).replace(",", ""))
                    # amt2 is balance — ignore
                    desc_part = remainder[:amt_m.start()].strip()
                    # Determine debit vs credit: look ahead or check context
                    # We'll store amt1 as unsigned and resolve direction below
                    pending_date     = date_str
                    pending_desc     = [desc_part] if desc_part else []
                    pending_txn_type = "debit"  # resolved below
                    # Look for a deposit marker on the next line
                    # Actually: in DBS layout, withdrawal col comes before deposit.
                    # We need to check if next non-empty line has another amount
                    # (meaning amt1 was withdrawal and next is balance,
                    #  or amt1 was deposit). We resolve by checking if there's
                    # a second amount line immediately after.
                    # Simpler: peek at next line
                    if i < len(lines):
                        nxt = lines[i].strip()
                        nxt_amt = DBS_ONE_AMOUNT.search(nxt)
                        if nxt_amt and not DBS_TXN_DATE.match(nxt):
                            # Next line is balance — amt1 is withdrawal
                            pending_txn_type = "debit"
                            i += 1  # consume balance line
                        else:
                            # amt1 might be deposit (no second amount line)
                            pending_txn_type = "debit"

                    desc = " ".join(pending_desc).strip()
                    transactions.append({
                        "date":        date_str,
                        "bank":        "DBS",
                        "account":     current_account,
                        "account_no":  f"****{current_acct_no[-4:]}" if current_acct_no else "",
                        "description": desc,
                        "amount":      round(-amt1, 2),
                        "type":        "debit",
                        "source_file": pdf_path.name,
                    })
                    flush_pending()

                else:
                    # No amount yet on this line — description continues
                    pending_date = date_str
                    pending_desc = [remainder] if remainder else []

            elif pending_date:
                # Continuation line for current transaction
                # Check if this line contains the amounts
                amt_m = DBS_AMOUNTS.search(line)
                one_m = DBS_ONE_AMOUNT.search(line)

                if amt_m:
                    amt1    = float(amt_m.group(1).replace(",", ""))
                    # amt2 is balance
                    desc_part = line[:amt_m.start()].strip()
                    if desc_part:
                        pending_desc.append(desc_part)

                    desc = " ".join(pending_desc).strip()

                    # Determine debit vs credit:
                    # Peek ahead — if next non-empty non-date line has an amount,
                    # that's the second column (deposit), so current is withdrawal.
                    # Simplest heuristic: if description contains "Deposit" or
                    # "FAST.*Receipt" or "PayNow.*from", it's a credit.
                    is_credit = bool(re.search(
                        r"deposit|receipt|salary|refund|cashback|interest|"
                        r"paynow.*from|fast.*from|giro.*from|credit",
                        desc, re.IGNORECASE
                    ))
                    amount   = amt1 if is_credit else -amt1
                    txn_type = "credit" if is_credit else "debit"

                    transactions.append({
                        "date":        pending_date,
                        "bank":        "DBS",
                        "account":     current_account,
                        "account_no":  f"****{current_acct_no[-4:]}" if current_acct_no else "",
                        "description": desc,
                        "amount":      round(amount, 2),
                        "type":        txn_type,
                        "source_file": pdf_path.name,
                    })
                    flush_pending()

                elif one_m and len(line.strip()) < 20:
                    # Likely a standalone amount line (balance column overflow)
                    # Skip — balance lines don't add transaction info
                    pass
                else:
                    # Pure description continuation
                    if line and not SKIP_LINES.search(line):
                        pending_desc.append(line)

    doc.close()
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
    """Quick scan of first page text to detect bank. Uses pymupdf for DBS font compatibility."""
    try:
        doc  = fitz.open(str(pdf_path))
        text = doc[0].get_text().lower()
        doc.close()
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