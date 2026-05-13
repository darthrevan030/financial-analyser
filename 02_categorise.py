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
    (r"salary|payroll|pay credit|temus|money pasar|ns pay",                  "Income", "Salary / NS Pay"),
    (r"giro.*salary.*mindef|giro.*salary.*saf|ps.*defence.*imprest|saf imprest", "Income", "Salary / NS Pay"),
    (r"interest credit|interest earned|savings bonus|cashback reward|rebate|cr interest|cashback", "Income", "Interest / Cashback"),
    (r"dividend|coupon payment|bond|sgs.*discount|t-bill.*discount|cdp.*bs",  "Income", "Investment Income"),
    (r"advice gift|gift deposit|inward telegraphic transfer\b",               "Income", "Gift / Other Income"),

    # ── Family allowance (must be before generic Transfers rule) ────────────────
    (r"paynow transfer vikram bhatia|fast.*vikram bhatia|ibft.*vikram bhatia|vikram bhatia.*paynow|vikram bhatia.*ibft|mr bhatia vikram|bhatia vikram.*driving fees|bhatia vikram.*wine|bhatia vikram na", "Income", "Family Allowance"),
    (r"paynow transfer mahiyu bhatia|fast.*mahiyu bhatia|ibft.*mahiyu bhatia|mahiyu bhatia.*paynow|mahiyu bhatia.*ibft|dadima kharchi mahiyu", "Income", "Family Allowance"),
    (r"paynow transfer goel shweta|fast.*goel shweta|ibft.*goel shweta|goel shweta.*paynow|goel shweta.*ibft|paynow transfer shweta|ibft.*shweta|shweta.*ibft", "Income", "Family Allowance"),

    # ── Own account / PayLah transfers ────────────────────────────────────────
    (r"top-up to paylah|send back from paylah|maxed out from paylah",         "Finance", "PayLah Transfer"),
    (r"advice funds transfer.*i-bank|271-410|120-512|072-015",                "Finance", "Own Account Transfer"),
    (r"fast.*samarth bhatia|samarth bhatia.*transfer|samarth bhatia.*ibft|ibftothr.*samarth|samarth.*ibftothr|si si ibftothr", "Finance", "Own Account Transfer"),
    (r"giro standing instruction.*samarth|standing instruction.*samarth",     "Finance", "Own Account Transfer"),
    (r"^samarth bhatia.*ibft|ibft.*samarth bhatia.*dbs bank",                 "Finance", "Own Account Transfer"),

    # ── Investments ───────────────────────────────────────────────────────────
    (r"saxo capital markets",                                                  "Investments", "Stocks / ETFs (SAXO)"),
    (r"interactive br sg|interactive brokers",                                "Investments", "Stocks / ETFs (IBKR)"),
    (r"asia wealth platform|remittance transfer.*asia wealth|0016rf",         "Investments", "Asia Wealth Platform"),
    (r"singapore government securities|sgs application|t-bill bs",            "Investments", "T-Bills / SGS"),
    (r"dividends.*cash distribution.*cdp|refund.*sgs.*discount",              "Investments", "T-Bills / SGS"),

    # ── Education / NTU ──────────────────────────────────────────────────────
    (r"nanyang technological university|ntu.*inv-|inv-.*ntu|xntu",            "Education", "Tuition / School Fees"),
    (r"ntu hostel aircon|www\.ntu\.edu|ntu - singpore",                       "Education", "NTU Misc"),
    (r"udemy|coursera|linkedin learn|skillsfuture|pluralsight",               "Education", "Online Courses"),
    (r"booklink|nts-booklink|junior page|popular bookstore",                  "Education", "Books / Learning Materials"),

    # ── Transport ─────────────────────────────────────────────────────────────
    (r"bus/mrt|transit link|ez-link|ezilink|transitlink|mrt\b|smrt|sbs transit|transit 3000", "Transport", "Public Transit"),
    (r"grab rides|grab\* [a-z0-9]|cabcharge|comfortdelgro driv|driving cen|aeroline|advice.*d2p.*comfortdelgro|d2pay.*comfortdelgro", "Transport", "Taxi / Ride-hailing"),
    (r"parking\.sg|hdb carpark|wilson parking|ura parking",                   "Transport", "Parking"),
    (r"scoot|jetstar|singapore airlines|\bsia \b|tiger air|airasia|cathay|lotte duty free", "Transport", "Flights"),

    # ── Food Delivery ─────────────────────────────────────────────────────────
    (r"grabfood|foodpanda|deliveroo|mcdelivery|uber.*eats",                   "Food & Drink", "Food Delivery"),

    # ── Fast Food ─────────────────────────────────────────────────────────────
    (r"mcdonald|mcdonalds|burger king|kfc\b|texas chicken|carl.s jr|mos burger|nando|subway\b|jollibee|stuff.d\b", "Food & Drink", "Fast Food"),

    # ── Hawker / Food Courts ──────────────────────────────────────────────────
    (r"kopitiam|food court|foodjunction|food junction|hawker|toast box|ya kun|old chang kee|koufu|pasta express|nts-pasta|sg f.b management|sg hawker|218 wang|big harvest noodle|ntu foodcourt|ntu canteen|105 drinks|fauzia muslim|ntu.*st\b|co-op cafe|canopy wanton|wok express|bbq house|fusion bowl|japanese korean|coffee break hd|esso-fairprice|encik tan|sembawang eating|sbtb stall|drinks stall", "Food & Drink", "Hawker / Coffee Shop"),

    # ── Restaurants ──────────────────────────────────────────────────────────
    (r"wok hey|saizeriya|hai di lao|pepper lunch|dabbawalla|indian curry|the tipsy cow|nuodle|hokkaido|maki-san|birds of paradise|timbre|shake shack|ajisen|baker.cook|le noir|piedra negra|hans im gluck|taco bar|shinya izakaya|bistro|naughtychef|gokoku|tapas 24|marche\b|din tai fung|ps cafe|chimichanga|alaturka|cheongheng|butter town|supreme ramen|dabbawalla|yew kee|net\*bakery|bakery cuisine|bakerycuisin|a hot hideout|suvai foods|indian\b.*stall", "Food & Drink", "Restaurant"),

    # ── Cafés ────────────────────────────────────────────────────────────────
    (r"starbucks|coffee bean|pacific coffee|spinelli|dutch colony|common man coffee|craftsmen coffee|coffee faculty|puzzle coffee|coffee smith|caffeine-xpress|lazy sloth|bean folks|venture drive coffee|ps cafe|daizu cafe|cafe carrera|rosso vino", "Food & Drink", "Café"),

    # ── Bubble Tea / Desserts ─────────────────────────────────────────────────
    (r"gong cha|gongcha|koi the|boba|tiger sugar|each.a.cup|tealive|cha time|sharetea|playmade|milksha|kind kones|mr coconut|chicha san chen|attea|chagee|an acai affair|randy indulgence|gelare|yole|mixue|le le bing|j\.co\b|llao llao|octobox|polar puffs|beard papa|nasty cookie|mr bean\b", "Food & Drink", "Bubble Tea / Dessert"),

    # ── Groceries ─────────────────────────────────────────────────────────────
    (r"fairprice|ntuc fp|\bntuc\b|giant\b|cold storage|sheng siong|prime supermarket|don don donki|donki|scarlett supermarket|abc bargain|nts-abc|dingo foods|better baker\b|four leaves|thekneadhouse|o bread|my bake studio|gourmet park|octobox", "Food & Drink", "Groceries"),

    # ── Convenience ───────────────────────────────────────────────────────────
    (r"7-eleven|7eleven|cheers holdings|cheers -",                            "Food & Drink", "Convenience Store"),

    # ── Shopping ──────────────────────────────────────────────────────────────
    (r"shopee singapore mp|shopee.*sg|lazada|amazon.*sg|amazon retail|amazon mktplc|2c2\*amazon", "Shopping", "Online Marketplace"),
    (r"uniqlo|h&m|\bzara\b|cotton on|pull.bear|topshop|g2000|bhg singapore|marks.*spencer|shein\b|typo-|by invite only|beauty language|lamy\b|gainswell|royal fragrances|pandora|sultan islamic|finest jewel|finest funan", "Shopping", "Clothing / Accessories"),
    (r"courts|harvey norman|gain city|challenger|best denki|t k foto|sp spinnaker|h2 hub timepiece|crystal time|gadgetbox|blitzwerks\b", "Shopping", "Electronics / Watches"),
    (r"guardian|watsons|unity pharmacy|heartland health|straits contact lens", "Health", "Pharmacy"),
    (r"nts-3tmobilestory|la mode hair|ming hairport|nts-la mode|sp neven eyewear", "Shopping", "Personal Care"),
    (r"ikea|home-fix|homefix|spotlight|daiso|miniso",                          "Shopping", "Home & Lifestyle"),
    (r"parkway|raffles hospital|mount elizabeth|polyclinic|sgh\b|nuh\b|ttsh|kkh\b|ntfgh", "Health", "Medical"),
    (r"prudential|great eastern|aia\b|aviva|manulife|tokio marine|income insurance", "Finance", "Insurance"),

    # ── Entertainment ─────────────────────────────────────────────────────────
    (r"steam|playstation|xbox|nintendo|epicgames|steamgames|paddle\.net.*supercell|google.*supercell|google.*clash|clash of clans|microsoft.*xbox|microsoft.*store|kickstarter|google snapchat", "Entertainment", "Gaming"),
    (r"shaw theatres|golden village|\bgv \b|filmgarde|cathay cineplexes|ticketmaster|singapore gp|kfi-arena|kf1 pte|superbowl|oche sg|sentosa express|singapore pub crawl|opvs|marquee singapore|gv tampines|alex warren", "Entertainment", "Events / Concerts"),
    (r"28mm studios|blitzwerks\b",                                             "Entertainment", "Photography"),

    # ── Subscriptions ─────────────────────────────────────────────────────────
    (r"spotify|netflix|disney|apple tv|youtube|hbo|dazn|mubi|flexcil|jetpacglobal|google chrome\b", "Subscriptions", "Streaming / Apps"),
    (r"github|vercel|netlify|digitalocean|\baws\b|google cloud|azure|aentry\b", "Subscriptions", "Cloud / Dev Tools"),

    # ── Finance / Bank ────────────────────────────────────────────────────────
    (r"cpf board|cpf contribution|medisave",                                   "Finance", "CPF"),
    (r"gov gov ibftothr|\biras\b",                                             "Misc", "Government / Statutory"),
    (r"giro standing instruction|giro.*salary\b|giro payments|giro.*collections", "Finance", "GIRO"),
    (r"advice remittance|telegraphic transfer|inward telegraphic|ft\d+mb.*:ib", "Finance", "Remittance"),
    (r"paynow transfer|fast\(othr\)|advice fast|ibft\|",                      "Finance", "Transfers"),
    (r"atm cash withdrawal|atm cashcard|cashcard.*top-up",                    "Finance", "Cash Withdrawal"),
    (r"shopeepay|fomo pay",                                                    "Finance", "E-wallet"),
    (r"fresh laundry|es laundry",                                              "Misc", "Laundry"),
    (r"singpost|courier|dhl|fedex|lalamove|federal express",                  "Misc", "Postage / Courier"),
    (r"lta road tax|passport|immigration",                                     "Misc", "Government / Statutory"),
    (r"donation|charity|giving\.sg|red cross",                                 "Misc", "Donations"),

    # ── NETS QR / NTS catch-all ───────────────────────────────────────────────
    (r"^nts-|^ntsqr ",                                                         "Shopping", "NETS Purchase"),

    # ── Standalone date codes (SCB value date artefacts) ─────────────────────
    (r"^\d{2}/\d{2}$",                                                         "Finance", "Transfers"),

    # ── Date-prefixed card transactions with no other match ───────────────────
    (r"^\d{2}/\d{2}[\s\-]",                                                    "Shopping", "Card Purchase"),
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