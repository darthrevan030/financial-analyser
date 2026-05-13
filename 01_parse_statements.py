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

    Two known layouts:
    - 2021+: date alone on its own line as DD/MM/YYYY
    - 2020:  date as 'DD Mon' (short, no year), currency on two separate lines
    Both: description lines follow, then amount alone, then balance alone.
    """
    transactions = []
    current_account = "DBS Account"
    current_acct_no = ""
    statement_year  = str(datetime.now().year)

    DATE_FULL   = re.compile(r"^(\d{2}/\d{2}/\d{4})\s*$")
    DATE_SHORT  = re.compile(r"^(\d{1,2}\s+[A-Za-z]{3})\s*$")   # e.g. "02 Apr"
    AMOUNT_ONLY = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}\s*$")
    YEAR_HDR    = re.compile(r"[Aa]s\s+at\s+\d{1,2}\s+[A-Za-z]+\s+(\d{4})")
    SKIP        = re.compile(
        r"^(Date|Description|Withdrawal|Deposit|Balance|CURRENCY|SINGAPORE DOLLAR|"
        r"Balance Brought Forward|Balance Carried Forward|Transaction Details|"
        r"Deposits|Loans|Credit Cards|Page \d|PDS|SG\d|DBS Co\.|DBS Bank|"
        r"Account Summary|ACCOUNT SUMMARY|ACCOUNT DETAILS|Summary of Currency|"
        r"Total:|SGD Equivalent|\(Base Currency\)|\(SGD Equivalent\)|"
        r"Account No\.|Consolidated Statement|CONSOLIDATED STATEMENT|"
        r"12 Marina|Marina Bay|www\.|For enquiries|1800-|outside Singapore|"
        r"MULTI CURRENCY|TOTAL\s+DEPOSITS|DEPOSITS$|LOANS$|"
        r"S/N:|Message for you|MESSAGE FOR YOU)$",
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
    NOISE = re.compile(
        r"^(S/N:|BLK |SINGAPORE \d|#0|\[www\.|For enquiries|1800|"
        r"outside Singapore|Reg\. No|Reg No|\(4\d+\))",
        re.IGNORECASE
    )

    doc = fitz.open(str(pdf_path))

    for page in doc:
        lines = [l.strip() for l in page.get_text().splitlines()]

        # Extract statement year from page header if present
        for line in lines[:10]:
            ym = YEAR_HDR.search(line)
            if ym:
                statement_year = ym.group(1)
                break

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
            if NOISE.match(line):
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

            # ── State machine ─────────────────────────────────────────────
            if state == "IDLE":
                if DATE_FULL.match(line):
                    txn_date = parse_date(line)
                    txn_desc = []; state = "DESC"
                elif DATE_SHORT.match(line):
                    txn_date = parse_date(f"{line.strip()} {statement_year}")
                    txn_desc = []; state = "DESC"

            elif state == "DESC":
                if DATE_FULL.match(line):
                    txn_date = parse_date(line)
                    txn_desc = []
                elif DATE_SHORT.match(line):
                    txn_date = parse_date(f"{line.strip()} {statement_year}")
                    txn_desc = []
                elif AMOUNT_ONLY.match(line):
                    amount_raw = line.strip()
                    # Next line is balance — skip it
                    if i < len(lines) and AMOUNT_ONLY.match(lines[i].strip()):
                        i += 1
                    if txn_date and txn_desc:
                        commit(amount_raw, txn_desc, txn_date)
                    txn_date = None; txn_desc = []; state = "IDLE"
                else:
                    if len(line) > 1 and not SKIP.match(line):
                        txn_desc.append(line)

    doc.close()
    return transactions


def parse_scb(pdf_path: Path) -> list[dict]:
    """
    Parse a Standard Chartered statement PDF using pymupdf.

    Two known layouts:

    OLD (up to ~Aug 2022, JumpStart):
      Columns jumbled as separate lines, amounts have trailing spaces for balance.
      Date: 'DD Mon' (short)
      Balance lines have trailing space(s); txn amount lines do not.
      Withdrawal marked by '−' (unicode minus) on its own line after amount.

    NEW (Sep 2022+):
      Full dates: '30 Sep 2022'
      After description lines, TWO consecutive bare numbers appear:
        first  = transaction amount (withdrawal or deposit)
        second = running balance
      Credits: CASHBACK, CR INTEREST, FAST(OTHR) without '−', PAYNOW, SALARY, etc.
      Withdrawals: everything else (BUS/MRT, merchant names, etc.)
      Page 3 is legend — skip it.
    """
    transactions = []
    account_type = "SCB Account"
    acct_no_raw  = ""
    statement_year = str(datetime.now().year)

    DATE_FULL   = re.compile(r"^(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\s*$")
    DATE_SHORT  = re.compile(r"^(\d{1,2}\s+[A-Za-z]{3})\s*$")
    AMOUNT_RE2  = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}\s*$")
    YEAR_HDR    = re.compile(r"Statement\s+Date\s*[:\-]\s*\d{1,2}\s+[A-Za-z]+\s+(\d{4})", re.I)
    ACCT_NO_RE  = re.compile(r"(\d{2}-\d{1}-\d{6}-\d)")
    SKIP_PAGE   = re.compile(
        r"Reconciling|Savings Account Transaction|Explanation of Abbrev|"
        r"Explanation of abbrevi|Balance as per|Add Total deposits|"
        r"Subtract|cheque book|Cheque.s. issued|Cash Deposit$|"
        r"Cash Withdrawal$|Transfer Deposit$|Transfer Withdrawal$|"
        r"Cheque Deposit$|ATM Cash|ATM Transfer|Standing Instruction$|"
        r"Salary$|Nobook|Contact Us|Personal Banking$|Business Banking$|"
        r"Priority Banking$|Commercial Banking$|Private Banking$|"
        r"Corporate and Institutional Banking$|Adjustment$|"
        r"Business Overdraft$|Cheque\(s\)$|Deposit$|Nets$|"
        r"Telegraphic Transfer$|Automated Teller|Business Credit|"
        r"Clearing$|Draft$|Reversal$|Withdrawal$|Cash Card|"
        r"Business Unsecured|Correction$|Debit$|Personal Credit|"
        r"branch and ATM",
        re.I
    )
    SKIP_LINE   = re.compile(
        r"^(Statement of Account|Page\s|Branch\s*:|Priority Banking|"
        r"Personal Banking|Business Banking|Commercial Banking|"
        r"Corporate and Institutional|GST Group|Reg\. No\.|Reg\. Add\.|"
        r"Note: If you note|If you have moved|BALANCE FROM PREVIOUS|"
        r"CLOSING BALANCE|VALUE DATE|SGD Balance|Deposit$|Withdrawal$|"
        r"Description$|Date$|Balance$|This statement serves|"
        r"Standard Chartered Bank|Deposit Insurance|Singapore dollar deposits|"
        r"are not insured|Your Statement of Account|Cashback Summary|"
        r"Mastercard Spend|Average Daily Balance$)",
        re.I
    )
    CREDIT_DESC = re.compile(
        r"cashback|cr interest|interest credit|incoming|fast\(othr\)|fast.*receipt|salary|payroll|refund|rebate|dividend|"
        r"reversal|returned|paynow|standing instruction.*cr|deposit$|"
        r"transfer.*in|credit$",
        re.I
    )
    NOISE_LINE  = re.compile(r"^(\s*[a-z]\s*|\s*[a-z]\.\s*|\s*[ivx]+\.\s*|\s*[\.\(\)]\s*)$")

    doc = fitz.open(str(pdf_path))

    for page_num, page in enumerate(doc):
        lines_raw = page.get_text().splitlines()
        lines = [l.strip() for l in lines_raw]

        # Skip legend/reconciliation/contact pages
        non_empty = [l for l in lines if l]
        if len(non_empty) < 5:
            continue
        # Check first 20 non-empty lines for skip signals
        sample = " ".join(non_empty[:20])
        if SKIP_PAGE.search(sample) and not DATE_FULL.match(non_empty[0] if non_empty else ""):
            # More careful: only skip if no transaction dates found
            has_dates = any(DATE_FULL.match(l) or DATE_SHORT.match(l) for l in lines)
            if not has_dates:
                continue

        # Detect format from first page header
        for line in lines[:20]:
            ym = YEAR_HDR.search(line)
            if ym:
                statement_year = ym.group(1)
            an = ACCT_NO_RE.search(line)
            if an:
                acct_no_raw = an.group(1)
            if re.match(r"^(JUMPSTART|BonusSaver|e\$aver|MySaver|Bonus\$aver|"
                        r"Salary Credit|Unlimited|Simply Cash|Platinum|"
                        r"EasyCredit|e-Saver)", line, re.I):
                account_type = f"SCB {line.strip()}"

        # Determine layout: new format has full dates like '30 Sep 2022'
        has_full_dates = any(DATE_FULL.match(l) for l in lines)

        # ── Tagged line pass ──────────────────────────────────────────────
        tagged = []
        for raw, stripped in zip(lines_raw, lines):
            if not stripped:
                continue
            if SKIP_LINE.match(stripped):
                continue
            if NOISE_LINE.match(stripped):
                continue
            if any(stripped == x for x in ['Cashback', 'Average Daily Balance',
                                             'Mastercard Spend']):
                continue

            if has_full_dates and DATE_FULL.match(stripped):
                tagged.append(('DATE', stripped))
            elif not has_full_dates and DATE_SHORT.match(stripped):
                tagged.append(('DATE', stripped))
            elif AMOUNT_RE2.match(stripped):
                # Old format: trailing space in raw line = balance
                if not has_full_dates and raw.rstrip('\n').endswith(' '):
                    tagged.append(('BAL', stripped))
                else:
                    tagged.append(('AMT', stripped))
            elif stripped in ('-', '\u2212', '\u2013', '−'):
                tagged.append(('MINUS', stripped))
            else:
                tagged.append(('TEXT', stripped))

        # ── State machine ─────────────────────────────────────────────────
        i = 0
        while i < len(tagged):
            tag, val = tagged[i]
            i += 1

            if tag != 'DATE':
                continue

            # Parse date
            if has_full_dates:
                txn_date = parse_date(val)
            else:
                txn_date = parse_date(f"{val} {statement_year}")
            if not txn_date:
                continue

            desc_parts = []
            txn_amount = None
            is_minus   = False

            while i < len(tagged):
                t2, v2 = tagged[i]

                if t2 == 'DATE':
                    break
                elif t2 == 'BAL':
                    i += 1
                    continue
                elif t2 == 'MINUS':
                    is_minus = True
                    i += 1
                elif t2 == 'AMT':
                    txn_amount = float(v2.replace(',', ''))
                    i += 1
                    if has_full_dates:
                        # New format: next AMT is the balance — skip it
                        if i < len(tagged) and tagged[i][0] == 'AMT':
                            i += 1
                    break
                else:  # TEXT
                    if not SKIP_LINE.match(v2):
                        desc_parts.append(v2)
                    i += 1

            if txn_amount is None or not desc_parts:
                continue

            desc = ' '.join(desc_parts).strip()
            # Strip SGD amount annotations like 'SGD 7.75' from desc
            desc = re.sub(r'\bSGD\s+[\d,]+\.\d{2}\b', '', desc).strip()

            if is_minus:
                is_cr = False
            else:
                is_cr = bool(CREDIT_DESC.search(desc))

            transactions.append({
                "date":        txn_date,
                "bank":        "Standard Chartered",
                "account":     account_type,
                "account_no":  f"****{acct_no_raw[-4:]}" if acct_no_raw else "",
                "description": desc.strip(),
                "amount":      round(txn_amount if is_cr else -txn_amount, 2),
                "type":        "credit" if is_cr else "debit",
                "source_file": pdf_path.name,
            })

    doc.close()
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

    seen = set()
    pdfs = []
    for p in sorted(STATEMENTS_DIR.glob("**/*.pdf")):
        resolved = str(p.resolve()).lower()
        if resolved not in seen:
            seen.add(resolved)
            pdfs.append(p)
    pdfs = sorted(pdfs, key=lambda p: p.name)
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