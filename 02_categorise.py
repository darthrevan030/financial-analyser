"""
Transaction Categoriser
Reads transactions.csv → adds a 'category' and 'subcategory' column.

Edit the RULES list below to refine for your own spending patterns.
Run after 01_parse_statements.py.

Usage:
    python 02_categorise.py
"""

import pandas as pd
import re
from pathlib import Path

INPUT_CSV  = Path("transactions.csv")
OUTPUT_CSV = Path("transactions_categorised.csv")

# ─── CATEGORY RULES ──────────────────────────────────────────────────────────
# Each rule: (regex pattern, category, subcategory)
# Rules are checked in order — first match wins.
# Add / edit freely. Patterns are case-insensitive.

RULES: list[tuple[str, str, str]] = [

    # ── Income ────────────────────────────────────────────────────────────────
    (r"salary|payroll|pay credit|ntu|temus|money pasar|saf|mindef|ns pay", "Income", "Salary / NS Pay"),
    (r"interest credit|interest earned|savings bonus|cashback|rebate",      "Income", "Interest / Cashback"),
    (r"dividend|coupon payment|bond",                                        "Income", "Investment Income"),
    (r"freelance|invoice|payment received",                                  "Income", "Freelance"),

    # ── Housing ───────────────────────────────────────────────────────────────
    (r"hdb|town council|conservancy|s&cc|service and conservancy",           "Housing", "Town Council / S&CC"),
    (r"rent|rental|landlord",                                                "Housing", "Rent"),
    (r"sp group|sp services|utilities|singapore power",                      "Housing", "Utilities"),
    (r"starhub|singtel|m1 |myrepublic|viewqwest|broadband|fibre",            "Housing", "Broadband / Phone"),

    # ── Food & Drink ──────────────────────────────────────────────────────────
    (r"grabfood|foodpanda|deliveroo|mcdelivery|kfc\.com",                    "Food & Drink", "Food Delivery"),
    (r"mcdonald|burger king|kfc|subway|jollibee|pizza|dominos|texas chicken","Food & Drink", "Fast Food"),
    (r"kopitiam|food court|hawker|toast box|ya kun|old chang kee",           "Food & Drink", "Hawker / Coffee Shop"),
    (r"starbucks|coffee bean|pacific coffee|spinelli|dutch colony",          "Food & Drink", "Café"),
    (r"ntuc fairprice|fairprice|giant|cold storage|sheng siong|prime super", "Food & Drink", "Groceries"),
    (r"don don donki|donki|marketplace|market place|wet market",             "Food & Drink", "Groceries"),
    (r"restaurant|dining|eatery|bistro|cafe|kitchen|grill|buffet",          "Food & Drink", "Restaurant"),
    (r"7-eleven|7eleven|cheers|watsons food|petrol kiosk food",             "Food & Drink", "Convenience Store"),

    # ── Transport ─────────────────────────────────────────────────────────────
    (r"grab\b|gojek|tada cab|comfort|citycab|prime taxi|transit link",       "Transport", "Taxi / Ride-hailing"),
    (r"ez-link|ezilink|transitlink|mrt|smrt|sbs transit|bus fare",          "Transport", "Public Transit"),
    (r"petrol|esso|shell|caltex|sinopec|spc fuel|bharat petroleum",          "Transport", "Petrol"),
    (r"car park|parking|ura parking|hdb carpark|wilson parking",             "Transport", "Parking"),
    (r"scoot|jetstar|singapore airlines|sia |tiger air|airasia|cathay",      "Transport", "Flights"),
    (r"chang[i] airport|changi travel|travel agent|klook|airbnb|booking\.com|agoda|hotels\.com|expedia", "Transport", "Travel / Accommodation"),

    # ── Shopping ──────────────────────────────────────────────────────────────
    (r"shopee|lazada|amazon|qoo10|carousell|taobao|aliexpress",              "Shopping", "Online Marketplace"),
    (r"uniqlo|h&m|zara|cotton on|pull&bear|topshop|g2000",                  "Shopping", "Clothing"),
    (r"apple store|apple\.com|iphone|mac |ipad|samsung store",              "Shopping", "Electronics"),
    (r"courts|harvey norman|gain city|challenger|best denki",                "Shopping", "Electronics"),
    (r"ikea|home-fix|homefix|spotlight|daiso|miniso",                        "Shopping", "Home & Lifestyle"),
    (r"guardian|watsons|unity|caring pharmacy",                              "Shopping", "Pharmacy / Health Products"),
    (r"ntuc\b|fairprice\b|giant\b|cold storage\b|sheng siong\b",            "Shopping", "Supermarket"),  # non-food items

    # ── Entertainment ─────────────────────────────────────────────────────────
    (r"netflix|spotify|disney\+|apple tv|youtube premium|hbo|dazn|mubi",    "Entertainment", "Streaming"),
    (r"shaw|cathay cineplexes|golden village|gv |filmgarde",                 "Entertainment", "Cinema"),
    (r"steam|playstation|xbox|nintendo|epicgames|gog\.com",                  "Entertainment", "Gaming"),
    (r"singapore zoo|night safari|gardens by the bay|sentosa|universal",     "Entertainment", "Attractions"),
    (r"concert|ticketmaster|sistic|sports hub|kallang",                      "Entertainment", "Events / Concerts"),
    (r"darts|pool|billiards|bowling|sports|gym|fitness|anytime fitness",     "Entertainment", "Sports / Fitness"),

    # ── Health ────────────────────────────────────────────────────────────────
    (r"polyclinic|sgh|nuh|ttsh|kkh|ntfgh|parkway|raffles hospital|mount e", "Health", "Medical"),
    (r"dental|dentist|orthodonti",                                           "Health", "Dental"),
    (r"pharmacy|guardian|watsons health",                                    "Health", "Pharmacy"),
    (r"medisave|cpf medisave|great eastern health|prudential health|aia",    "Health", "Health Insurance"),

    # ── Education ─────────────────────────────────────────────────────────────
    (r"ntu |nanyang tech|student fee|exam fee|tuition fee|course fee",       "Education", "Tuition / School Fees"),
    (r"udemy|coursera|linkedin learn|skillsfuture|pluralsight",              "Education", "Online Courses"),
    (r"books|kinokuniya|popular bookstore|times bookstore|amazon kindle",    "Education", "Books / Learning Materials"),

    # ── Finance ───────────────────────────────────────────────────────────────
    (r"cpf contribution|cpf ordinary|cpf special|medisave top.?up",         "Finance", "CPF"),
    (r"insurance|great eastern|prudential|income insurance|aia|aviva|manulife|tokio marine", "Finance", "Insurance"),
    (r"giro|standing instruction|transfer to|funds transfer|paynow|fast transfer", "Finance", "Transfers"),
    (r"investment|fsm|phillip securities|tiger broker|moomoo|syfe|endowus|stashaway", "Finance", "Investments"),
    (r"atm withdrawal|cash withdrawal|cash advance",                         "Finance", "Cash Withdrawal"),
    (r"annual fee|late charge|finance charge|interest charge|bank charge",   "Finance", "Bank Fees & Charges"),
    (r"credit card payment|card payment|full payment",                       "Finance", "Credit Card Payment"),

    # ── Subscriptions / SaaS ──────────────────────────────────────────────────
    (r"github|vercel|netlify|digitalocean|aws|google cloud|azure",           "Subscriptions", "Cloud / Dev Tools"),
    (r"notion|figma|adobe|canva|microsoft 365|office 365|dropbox|icloud",    "Subscriptions", "Productivity Tools"),
    (r"chatgpt|openai|anthropic|midjourney|perplexity",                      "Subscriptions", "AI Tools"),
    (r"google one|google storage|apple storage",                             "Subscriptions", "Cloud Storage"),

    # ── Miscellaneous ─────────────────────────────────────────────────────────
    (r"donation|charity|giving\.sg|red cross|spo|flag day",                  "Misc", "Donations / Charity"),
    (r"post office|singpost|courier|dhl|fedex|lalamove",                     "Misc", "Postage / Courier"),
    (r"government|iras|iras gst|lta road tax|passport|immigration",          "Misc", "Government / Taxes"),
]


def categorise(description: str) -> tuple[str, str]:
    desc_lower = description.lower()
    for pattern, category, subcategory in RULES:
        if re.search(pattern, desc_lower):
            return category, subcategory
    return "Uncategorised", "Uncategorised"


def main():
    if not INPUT_CSV.exists():
        print(f"❌  {INPUT_CSV} not found. Run 01_parse_statements.py first.")
        return

    df = pd.read_csv(INPUT_CSV, parse_dates=["date"])
    print(f"  Loaded {len(df):,} transactions from {INPUT_CSV}")

    df[["category", "subcategory"]] = df["description"].apply(
        lambda d: pd.Series(categorise(str(d)))
    )

    uncategorised = df[df["category"] == "Uncategorised"]
    pct = len(uncategorised) / len(df) * 100

    df.to_csv(OUTPUT_CSV, index=False)

    print(f"\n  Category breakdown:")
    summary = df.groupby("category").size().sort_values(ascending=False)
    for cat, count in summary.items():
        bar = "█" * (count * 30 // len(df))
        print(f"    {cat:<28} {count:>5}  {bar}")

    print(f"\n  ⚠️  Uncategorised: {len(uncategorised):,} ({pct:.1f}%)")
    if len(uncategorised) > 0:
        print(f"      Top uncategorised descriptions:")
        top = uncategorised["description"].value_counts().head(15)
        for desc, cnt in top.items():
            print(f"        [{cnt:>3}x]  {desc[:70]}")
        print(f"\n      → Add matching rules to RULES in this file and re-run.")

    print(f"\n  ✅  Saved to {OUTPUT_CSV}")
    print(f"      Next step: run  03_analyse.py")


if __name__ == "__main__":
    main()
