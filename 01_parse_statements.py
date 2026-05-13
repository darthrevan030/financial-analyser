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
SCB_DATE   = re.compile(r"(\d{2}\s+[A-Za-z]{3}\s+\d{4}|\d{2}/\d{2}/\d{4}|\d{2}\s+[A-Za-z]{3})")

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

    Actual per-line structure (verified from real statements):
      '04/04/2021'                       <- date alone on its own line
      'Advice FAST Payment / Receipt'    <- description line(s)
      'PAYNOW TRANSFER'
      "TO: ASIA WEALTH PLATFORM- CLIENT'S"
      '7RNRG223'
      'OTHER'
      '100.00 '                          <- amount (withdrawal OR deposit)
      '2,522.25  '                       <- balance (consumed + discarded)

    State machine: IDLE -> DATE_SEEN -> collecting DESC -> AMOUNT_SEEN -> commit
    """
    transactions = []
    current_account = "DBS Account"
    current_acct_no = ""

    DATE_ONLY   = re.compile(r"^(\d{2}/\d{2}/\d{4})\s*$")
    AMOUNT_ONLY = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}\s*$")
    SKIP        = re.compile(
        r"^(Date|Description|Withdrawal|Deposit|Balance|CURRENCY|"
        r"Balance Brought Forward|Transaction Details|Deposits|Loans|"
        r"Credit Cards|Page \d|PDS_|SG\d|DBS Co\.|Account Summary|"
        r"Summary of Currency|Total:|SGD Equivalent|\(Base Currency\)|"
        r"\(SGD Equivalent\)|Account No\.|Consolidated Statement)$",
        re.IGNORECASE
    )
    ACCT_HDR = re.compile(
        r"^(My Account|Multiplier|MySavings|eMySavings|Autosave|"
        r"POSB Savings|Current Account|Cashline|Visa Platinum|"
        r"Mastercard|Debit|Credit Card|Pocket Money|MultiCurrency|"
        r"DBS [\w ]+Account|DBS [\w ]+Card)",
        re.IGNORECASE
    )
    ACCT_NO = re.compile(r"(\d{3}-\d{6}-\d)")
    CREDIT_DESC = re.compile(
        r"incoming|from:|paynow transfer$|fast.*receipt|giro.*cr|"
        r"salary|payroll|interest earned|refund|cashback|rebate|dividend|"
        r"reversal|returned|NS PAY|mindef|maxed out from paylah",
        re.IGNORECASE
    )

    doc = fitz.open(str(pdf_path))

    for page in doc:
        lines = [l.strip() for l in page.get_text().splitlines()]

        state    = "IDLE"
        txn_date = None
        txn_desc = []

        def commit(amount_raw, desc_lines, date):
            amt  = float(amount_raw.replace(",", ""))
            desc = " ".join(desc_lines).strip()
            is_cr = bool(CREDIT_DESC.search(desc))
            transactions.append({
                "date":        date,
                "bank":        "DBS",
                "account":     current_account,
                "account_no":  f"****{current_acct_no[-4:]}" if current_acct_no else "",
                "description": desc,
                "amount":      round(amt if is_cr else -amt, 2),
                "type":        "credit" if is_cr else "debit",
                "source_file": pdf_path.name,
            })

        i = 0
        while i < len(lines):
            line = lines[i]
            i += 1

            if not line:
                continue

            # Account header
            if ACCT_HDR.match(line) and len(line) < 80:
                current_account = line
                for k in range(i, min(i + 4, len(lines))):
                    no_m = ACCT_NO.search(lines[k])
                    if no_m:
                        current_acct_no = no_m.group(1)
                        break
                state = "IDLE"; txn_date = None; txn_desc = []
                continue

            if SKIP.match(line):
                continue
            if any(x in line for x in ["S/N:", "BLK ", "SINGAPORE ", "#0", "Reg. No", "Reg No"]):
                continue

            if state == "IDLE":
                if DATE_ONLY.match(line):
                    txn_date = parse_date(line)
                    txn_desc = []
                    state    = "DESC"

            elif state == "DESC":
                if DATE_ONLY.match(line):
                    # New date before we saw an amount — reset
                    txn_date = parse_date(line)
                    txn_desc = []

                elif AMOUNT_ONLY.match(line):
                    amount_raw = line.strip()
                    # Next line is the balance — skip it
                    if i < len(lines) and AMOUNT_ONLY.match(lines[i].strip()):
                        i += 1
                    if txn_date and txn_desc:
                        commit(amount_raw, txn_desc, txn_date)
                    txn_date = None; txn_desc = []; state = "IDLE"

                else:
                    if len(line) > 1:
                        txn_desc.append(line)

    doc.close()
    return transactions

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

ISO_DATE_FILENAME = re.compile(r"^\d{8}\.pdf$", re.IGNORECASE)

def detect_bank(pdf_path: Path) -> str:
    """Detect bank from filename pattern or PDF content."""
    # SCB statements download with ISO date filenames e.g. 20221231.pdf
    if ISO_DATE_FILENAME.match(pdf_path.name):
        return "SCB"
    # DBS statements download with descriptive names containing DBS/POSB
    if "dbs" in pdf_path.name.lower() or "posb" in pdf_path.name.lower():
        return "DBS"
    # Fallback: scan PDF content
    try:
        doc  = fitz.open(str(pdf_path))
        text = " ".join(doc[i].get_text().lower() for i in range(min(3, len(doc))))
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