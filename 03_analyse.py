"""
Financial Analysis & Charts
Reads transactions_categorised.csv → generates full analysis + HTML dashboard.

Usage:
    python 03_analyse.py

Outputs:
    - analysis_report.txt      Plain-text summary of all key metrics
    - charts/                  PNG charts (monthly trends, categories, etc.)
    - dashboard.html           Self-contained interactive HTML dashboard
"""

import pandas as pd
import matplotlib
matplotlib.use("Agg")   # non-interactive backend — safe for all platforms
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from pathlib import Path
import json, textwrap
from datetime import datetime

INPUT_CSV   = Path("transactions_categorised.csv")
REPORT_TXT  = Path("analysis_report.txt")
CHARTS_DIR  = Path("charts")
DASHBOARD   = Path("dashboard.html")

CHARTS_DIR.mkdir(exist_ok=True)

# Singapore dollar formatting
def sgd(val: float) -> str:
    return f"S${val:,.2f}"

# ─── LOAD DATA ────────────────────────────────────────────────────────────────

# Categories that represent internal transfers / not real cashflow
EXCLUDE_CATS = {
    "Finance",   # own account transfers, GIRO SIs, FAST to self, investments
}
# Within Finance, these subcategories DO represent real outflows worth tracking
INCLUDE_FINANCE_SUBS = {
    "Investments",  # money leaving to brokerage — real deployment
    "Insurance",
    "Bank Fees & Charges",
}

INTERNAL_SUBCATEGORIES = {
    "Own Account Transfer",
    "PayLah Transfer",
    "Transfers",
    "GIRO",
    "Remittance",
    "E-wallet",
}

INVESTMENT_SUBCATEGORIES = {
    "Stocks / ETFs (SAXO)",
    "Stocks / ETFs (IBKR)",
    "T-Bills / SGS",
    "Asia Wealth Platform",
}

def investments(df: pd.DataFrame) -> pd.DataFrame:
    """Return only investment transactions."""
    return df[df["subcategory"].isin(INVESTMENT_SUBCATEGORIES)]

def real(df: pd.DataFrame) -> pd.DataFrame:
    """Exclude internal transfers and investments — only real consumption spending."""
    return df[
        ~df["subcategory"].isin(INTERNAL_SUBCATEGORIES) &
        ~df["subcategory"].isin(INVESTMENT_SUBCATEGORIES)
    ]

def load() -> pd.DataFrame:
    df = pd.read_csv(INPUT_CSV, parse_dates=["date"])
    df["year"]       = df["date"].dt.year
    df["month"]      = df["date"].dt.to_period("M")
    df["month_str"]  = df["date"].dt.strftime("%Y-%m")
    df["year_month"] = df["date"].dt.to_period("M")

    # Mark rows that are real cashflow (exclude internal transfers)
    is_finance     = df["category"] == "Finance"
    is_keep_finance = df["subcategory"].isin(INCLUDE_FINANCE_SUBS)
    df["is_real"]  = ~is_finance | is_keep_finance

    df["is_income"]  = df["is_real"] & (df["amount"] > 0)
    df["is_expense"] = df["is_real"] & (df["amount"] < 0)
    return df

# ─── CHARTS ───────────────────────────────────────────────────────────────────

PALETTE = ["#2E86AB", "#A23B72", "#F18F01", "#C73E1D", "#3B1F2B",
           "#44BBA4", "#E94F37", "#393E41", "#F5A623", "#7B2D8B"]

def chart_monthly_cashflow(df: pd.DataFrame):
    df = real(df)
    monthly = df.groupby("month_str").agg(
        income  = ("amount", lambda x: x[x > 0].sum()),
        expense = ("amount", lambda x: abs(x[x < 0].sum())),
    ).reset_index()
    monthly["net"] = monthly["income"] - monthly["expense"]

    fig, ax = plt.subplots(figsize=(16, 5))
    x = range(len(monthly))
    ax.bar(x, monthly["income"],  label="Income",  color="#44BBA4", alpha=0.85, width=0.4, align="edge")
    ax.bar(x, -monthly["expense"], label="Expense", color="#E94F37", alpha=0.85, width=-0.4, align="edge")
    ax.plot(x, monthly["net"], color="#2E86AB", linewidth=2, marker="o", markersize=3, label="Net")
    ax.axhline(0, color="black", linewidth=0.5)

    # X-axis: show every 3rd label to avoid crowding
    tick_positions = list(range(0, len(monthly), 3))
    ax.set_xticks(tick_positions)
    ax.set_xticklabels([monthly["month_str"].iloc[i] for i in tick_positions], rotation=45, ha="right", fontsize=8)

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"S${v:,.0f}"))
    ax.set_title("Monthly Cash Flow (7-Year Overview)", fontsize=14, fontweight="bold")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(CHARTS_DIR / "01_monthly_cashflow.png", dpi=150)
    plt.close(fig)
    print("  ✓  charts/01_monthly_cashflow.png")


def chart_annual_summary(df: pd.DataFrame):
    df = real(df)
    annual = df.groupby("year").agg(
        income  = ("amount", lambda x: x[x > 0].sum()),
        expense = ("amount", lambda x: abs(x[x < 0].sum())),
    ).reset_index()
    annual["savings_rate"] = ((annual["income"] - annual["expense"]) / annual["income"] * 100).replace([float("inf"), float("-inf")], 0).fillna(0)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # Grouped bar — income vs expense
    w = 0.35
    years = annual["year"].astype(str)
    x = np.arange(len(years))
    ax1.bar(x - w/2, annual["income"],  width=w, label="Income",  color="#44BBA4")
    ax1.bar(x + w/2, annual["expense"], width=w, label="Expense", color="#E94F37")
    ax1.set_xticks(x); ax1.set_xticklabels(years)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"S${v/1000:.0f}k"))
    ax1.set_title("Annual Income vs Expense", fontweight="bold")
    ax1.legend(); ax1.grid(axis="y", alpha=0.3)

    # Savings rate — allow negatives
    colors_sr = ["#2E86AB" if v >= 0 else "#E94F37" for v in annual["savings_rate"]]
    ax2.bar(x, annual["savings_rate"], color=colors_sr)
    ax2.set_xticks(x); ax2.set_xticklabels(years)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax2.set_title("Annual Savings Rate", fontweight="bold")
    ax2.axhline(0, color="black", linewidth=0.8)
    ax2.grid(axis="y", alpha=0.3)
    for i, v in enumerate(annual["savings_rate"]):
        offset = 1 if v >= 0 else -4
        ax2.text(i, v + offset, f"{v:.1f}%", ha="center", fontsize=9)

    fig.tight_layout()
    fig.savefig(CHARTS_DIR / "02_annual_summary.png", dpi=150)
    plt.close(fig)
    print("  ✓  charts/02_annual_summary.png")


def chart_category_breakdown(df: pd.DataFrame):
    df = real(df)
    expenses = df[df["amount"] < 0].copy()
    expenses["amount_abs"] = expenses["amount"].abs()
    by_cat = expenses.groupby("category")["amount_abs"].sum().sort_values(ascending=False)
    by_cat = by_cat[by_cat.index != "Finance"]  # exclude internal transfers

    fig, ax = plt.subplots(figsize=(10, 6))
    colors = PALETTE[:len(by_cat)]
    wedges, texts, autotexts = ax.pie(
        by_cat.values, labels=None, autopct="%1.1f%%",
        colors=colors, startangle=140, pctdistance=0.82,
        wedgeprops=dict(width=0.5)
    )
    ax.legend(wedges, [f"{c}  ({sgd(v)})" for c, v in zip(by_cat.index, by_cat.values)],
              loc="center left", bbox_to_anchor=(1, 0.5), fontsize=9)
    ax.set_title("Total Spend by Category (7 Years)", fontweight="bold")
    fig.tight_layout()
    fig.savefig(CHARTS_DIR / "03_category_breakdown.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  ✓  charts/03_category_breakdown.png")


def chart_top_merchants(df: pd.DataFrame):
    df = real(df)
    expenses = df[df["amount"] < 0].copy()
    expenses["amount_abs"] = expenses["amount"].abs()
    top = expenses.groupby("description")["amount_abs"].sum().sort_values(ascending=False).head(20)

    fig, ax = plt.subplots(figsize=(10, 7))
    labels = [textwrap.shorten(d, width=45) for d in top.index]
    bars = ax.barh(labels[::-1], top.values[::-1], color="#2E86AB")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"S${v:,.0f}"))
    ax.set_title("Top 20 Merchants / Payees by Total Spend", fontweight="bold")
    ax.grid(axis="x", alpha=0.3)
    for bar, val in zip(bars, top.values[::-1]):
        ax.text(bar.get_width() + 50, bar.get_y() + bar.get_height()/2,
                sgd(val), va="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(CHARTS_DIR / "04_top_merchants.png", dpi=150)
    plt.close(fig)
    print("  ✓  charts/04_top_merchants.png")


def chart_spending_heatmap(df: pd.DataFrame):
    """Heatmap of monthly spend by category across years."""
    df = real(df)
    expenses = df[(df["amount"] < 0) & (df["category"] != "Finance")].copy()
    expenses["amount_abs"] = expenses["amount"].abs()
    pivot = expenses.pivot_table(
        index="category", columns="year", values="amount_abs", aggfunc="sum"
    ).fillna(0)

    fig, ax = plt.subplots(figsize=(12, max(5, len(pivot) * 0.5)))
    im = ax.imshow(pivot.values, aspect="auto", cmap="YlOrRd")
    ax.set_xticks(range(len(pivot.columns))); ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index)));  ax.set_yticklabels(pivot.index)
    plt.colorbar(im, ax=ax, label="S$ Spend")
    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            val = pivot.values[i, j]
            ax.text(j, i, f"{val/1000:.1f}k" if val >= 1000 else f"{val:.0f}",
                    ha="center", va="center", fontsize=7,
                    color="white" if val > pivot.values.max() * 0.6 else "black")
    ax.set_title("Annual Spend Heatmap by Category (S$)", fontweight="bold")
    fig.tight_layout()
    fig.savefig(CHARTS_DIR / "05_spending_heatmap.png", dpi=150)
    plt.close(fig)
    print("  ✓  charts/05_spending_heatmap.png")


def chart_running_balance(df: pd.DataFrame):
    """Approximate running net worth proxy (cumulative net cash flow)."""
    monthly_net = df.groupby("month_str")["amount"].sum().reset_index()
    monthly_net.columns = ["month", "net"]
    monthly_net["cumulative"] = monthly_net["net"].cumsum()

    fig, ax = plt.subplots(figsize=(16, 4))
    ax.fill_between(range(len(monthly_net)), monthly_net["cumulative"], alpha=0.3, color="#2E86AB")
    ax.plot(range(len(monthly_net)), monthly_net["cumulative"], color="#2E86AB", linewidth=2)

    tick_pos = list(range(0, len(monthly_net), 6))
    ax.set_xticks(tick_pos)
    ax.set_xticklabels([monthly_net["month"].iloc[i] for i in tick_pos], rotation=45, ha="right", fontsize=8)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"S${v:,.0f}"))
    ax.set_title("Cumulative Net Cash Flow Over Time", fontweight="bold")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(CHARTS_DIR / "06_cumulative_cashflow.png", dpi=150)
    plt.close(fig)
    print("  ✓  charts/06_cumulative_cashflow.png")


# ─── TEXT REPORT ──────────────────────────────────────────────────────────────

def generate_report(df: pd.DataFrame) -> str:
    df_full = df.copy()
    df = real(df)
    lines = []
    sep = "─" * 60

    def h(title): lines.append(f"\n{sep}\n  {title}\n{sep}")
    def row(label, val): lines.append(f"  {label:<38} {val}")

    lines.append("PERSONAL FINANCE REPORT")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"Data range: {df['date'].min().date()} → {df['date'].max().date()}")

    income  = df[df["amount"] > 0]["amount"].sum()
    expense = df[df["amount"] < 0]["amount"].abs().sum()
    net     = income - expense
    months  = df["month"].nunique()

    h("OVERALL SUMMARY")
    row("Total income",         sgd(income))
    row("Total expenditure",    sgd(expense))
    row("Net (income - spend)", sgd(net))
    row("Overall savings rate", f"{net/income*100:.1f}%" if income else "N/A")
    row("Months covered",       str(months))
    row("Avg monthly income",   sgd(income / months) if months else "N/A")
    row("Avg monthly spend",    sgd(expense / months) if months else "N/A")
    row("Avg monthly savings",  sgd(net / months) if months else "N/A")
    row("Total transactions",   f"{len(df):,}")

    h("ANNUAL BREAKDOWN")
    annual = df.groupby("year").agg(
        income  = ("amount", lambda x: x[x > 0].sum()),
        expense = ("amount", lambda x: x[x < 0].abs().sum()),
    )
    annual["savings"] = annual["income"] - annual["expense"]
    annual["rate"]    = (annual["savings"] / annual["income"] * 100).round(1)
    lines.append(f"\n  {'Year':<8} {'Income':>14} {'Expense':>14} {'Savings':>14} {'Rate':>8}")
    lines.append(f"  {'─'*8} {'─'*14} {'─'*14} {'─'*14} {'─'*8}")
    for yr, r in annual.iterrows():
        lines.append(f"  {yr:<8} {sgd(r['income']):>14} {sgd(r['expense']):>14} {sgd(r['savings']):>14} {r['rate']:>7.1f}%")

    h("SPEND BY CATEGORY (ALL TIME)")
    expenses = df[df["amount"] < 0]
    by_cat   = expenses.groupby("category")["amount"].apply(lambda x: x.abs().sum()).sort_values(ascending=False)
    total_exp = by_cat.sum()
    lines.append(f"\n  {'Category':<28} {'Total':>12} {'% of Spend':>12}")
    lines.append(f"  {'─'*28} {'─'*12} {'─'*12}")
    for cat, val in by_cat.items():
        lines.append(f"  {cat:<28} {sgd(val):>12} {val/total_exp*100:>11.1f}%")

    h("TOP 10 SUBCATEGORIES BY SPEND")
    by_sub = expenses.groupby(["category", "subcategory"])["amount"].apply(lambda x: x.abs().sum()).sort_values(ascending=False).head(10)
    for (cat, sub), val in by_sub.items():
        lines.append(f"  {cat} → {sub:<35} {sgd(val)}")

    h("TOP 15 MERCHANTS / PAYEES")
    top_merch = expenses.groupby("description")["amount"].apply(lambda x: x.abs().sum()).sort_values(ascending=False).head(15)
    for desc, val in top_merch.items():
        lines.append(f"  {textwrap.shorten(desc, 45):<47} {sgd(val)}")

    h("INVESTMENTS (EXCLUDED FROM SPEND)")
    inv = investments(df_full)
    inv_out = inv[inv["amount"] < 0]["amount"].abs().sum()
    inv_in  = inv[inv["amount"] > 0]["amount"].sum()
    row("Total invested (outflows)",  sgd(inv_out))
    row("Total returned (inflows)",   sgd(inv_in))
    row("Net invested",               sgd(inv_out - inv_in))
    lines.append("")
    by_inv = inv.groupby("subcategory")["amount"].apply(
        lambda x: pd.Series({"out": x[x<0].abs().sum(), "in": x[x>0].sum()})
    ).unstack(fill_value=0)
    for sub in by_inv.index:
        out = by_inv.loc[sub, "out"] if "out" in by_inv.columns else 0
        ins = by_inv.loc[sub, "in"]  if "in"  in by_inv.columns else 0
        lines.append(f"  {sub:<35} out: {sgd(out):>12}   in: {sgd(ins):>12}")

    h("UNCATEGORISED TRANSACTIONS")
    unc = df[df["category"] == "Uncategorised"]
    row("Count", f"{len(unc):,} ({len(unc)/len(df)*100:.1f}%)")
    if len(unc) > 0:
        lines.append("\n  Top uncategorised descriptions:")
        for desc, cnt in unc["description"].value_counts().head(10).items():
            lines.append(f"    [{cnt:>3}x]  {textwrap.shorten(desc, 65)}")

    h("POTENTIAL RECURRING SUBSCRIPTIONS")
    # Transactions appearing 6+ times from same merchant
    freq = df.groupby("description").agg(count=("amount", "count"), avg=("amount", "mean"))
    subs = freq[(freq["count"] >= 6) & (freq["avg"] < 0) & (freq["avg"].abs() < 500)].sort_values("count", ascending=False)
    if len(subs) > 0:
        for desc, r in subs.head(15).iterrows():
            lines.append(f"  [{r['count']:>3}x]  ~{sgd(abs(r['avg']))}/occurrence  {textwrap.shorten(desc, 50)}")
    else:
        lines.append("  None detected.")

    return "\n".join(lines)


# ─── HTML DASHBOARD ───────────────────────────────────────────────────────────

def generate_dashboard(df: pd.DataFrame):
    df = real(df)
    """Generate a self-contained interactive HTML dashboard using Chart.js."""

    # Prepare data
    monthly = df.groupby("month_str").agg(
        income  = ("amount", lambda x: x[x > 0].sum()),
        expense = ("amount", lambda x: x[x < 0].abs().sum()),
    ).reset_index()

    annual = df.groupby("year").agg(
        income  = ("amount", lambda x: x[x > 0].sum()),
        expense = ("amount", lambda x: x[x < 0].abs().sum()),
    ).reset_index()
    annual["savings_rate"] = ((annual["income"] - annual["expense"]) / annual["income"] * 100).clip(0)

    cat_spend = df[df["amount"] < 0].groupby("category")["amount"].apply(lambda x: x.abs().sum()).sort_values(ascending=False)
    cat_spend = cat_spend[cat_spend.index != "Finance"].head(10)

    monthly_labels = json.dumps(monthly["month_str"].tolist())
    monthly_income = json.dumps(monthly["income"].round(2).tolist())
    monthly_expense = json.dumps(monthly["expense"].round(2).tolist())

    annual_labels = json.dumps(annual["year"].astype(str).tolist())
    annual_income = json.dumps(annual["income"].round(2).tolist())
    annual_expense = json.dumps(annual["expense"].round(2).tolist())
    annual_savings = json.dumps(annual["savings_rate"].round(1).tolist())

    cat_labels = json.dumps(cat_spend.index.tolist())
    cat_values = json.dumps(cat_spend.round(2).tolist())

    # Summary stats
    total_income  = df[df["amount"] > 0]["amount"].sum()
    total_expense = df[df["amount"] < 0]["amount"].abs().sum()
    net           = total_income - total_expense
    savings_rate  = net / total_income * 100 if total_income else 0
    months        = df["month"].nunique()

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Personal Finance Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f172a; color: #e2e8f0; padding: 24px; }}
  h1 {{ font-size: 1.6rem; font-weight: 700; margin-bottom: 4px; }}
  .subtitle {{ color: #94a3b8; font-size: 0.85rem; margin-bottom: 24px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px; margin-bottom: 28px; }}
  .card {{ background: #1e293b; border-radius: 12px; padding: 18px; }}
  .card .label {{ font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; letter-spacing: .05em; }}
  .card .value {{ font-size: 1.4rem; font-weight: 700; margin-top: 4px; }}
  .card .value.green {{ color: #4ade80; }}
  .card .value.red   {{ color: #f87171; }}
  .card .value.blue  {{ color: #60a5fa; }}
  .charts {{ display: grid; grid-template-columns: 1fr; gap: 24px; }}
  .chart-box {{ background: #1e293b; border-radius: 12px; padding: 20px; }}
  .chart-box h2 {{ font-size: 0.95rem; color: #94a3b8; margin-bottom: 16px; }}
  canvas {{ max-height: 340px; }}
  @media (min-width: 900px) {{
    .charts {{ grid-template-columns: 1fr 1fr; }}
    .chart-box.wide {{ grid-column: span 2; }}
  }}
</style>
</head>
<body>
<h1>Personal Finance Dashboard</h1>
<p class="subtitle">
  {df['date'].min().strftime('%b %Y')} – {df['date'].max().strftime('%b %Y')}
  &nbsp;·&nbsp; {months} months
  &nbsp;·&nbsp; {len(df):,} transactions
  &nbsp;·&nbsp; Generated {datetime.now().strftime('%d %b %Y')}
</p>

<div class="cards">
  <div class="card">
    <div class="label">Total Income</div>
    <div class="value green">S${total_income:,.0f}</div>
  </div>
  <div class="card">
    <div class="label">Total Spent</div>
    <div class="value red">S${total_expense:,.0f}</div>
  </div>
  <div class="card">
    <div class="label">Net Saved</div>
    <div class="value blue">S${net:,.0f}</div>
  </div>
  <div class="card">
    <div class="label">Savings Rate</div>
    <div class="value {'green' if savings_rate >= 20 else 'red'}">{savings_rate:.1f}%</div>
  </div>
  <div class="card">
    <div class="label">Avg Monthly Income</div>
    <div class="value">S${total_income/months:,.0f}</div>
  </div>
  <div class="card">
    <div class="label">Avg Monthly Spend</div>
    <div class="value">S${total_expense/months:,.0f}</div>
  </div>
</div>

<div class="charts">
  <div class="chart-box wide">
    <h2>Monthly Cash Flow</h2>
    <canvas id="cashflow"></canvas>
  </div>
  <div class="chart-box">
    <h2>Annual Savings Rate</h2>
    <canvas id="savings"></canvas>
  </div>
  <div class="chart-box">
    <h2>Spend by Category</h2>
    <canvas id="categories"></canvas>
  </div>
  <div class="chart-box wide">
    <h2>Annual Income vs Expense</h2>
    <canvas id="annual"></canvas>
  </div>
</div>

<script>
const COLORS = ["#60a5fa","#f87171","#4ade80","#fbbf24","#a78bfa",
                "#34d399","#fb923c","#818cf8","#e879f9","#2dd4bf"];

// Monthly cashflow
new Chart(document.getElementById("cashflow"), {{
  type: "bar",
  data: {{
    labels: {monthly_labels},
    datasets: [
      {{ label: "Income",  data: {monthly_income},  backgroundColor: "#4ade8055", borderColor: "#4ade80", borderWidth: 1 }},
      {{ label: "Expense", data: {monthly_expense}, backgroundColor: "#f8717155", borderColor: "#f87171", borderWidth: 1 }},
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ labels: {{ color: "#e2e8f0" }} }} }},
    scales: {{
      x: {{ ticks: {{ color: "#94a3b8", maxTicksLimit: 24 }}, grid: {{ color: "#1e293b" }} }},
      y: {{ ticks: {{ color: "#94a3b8", callback: v => "S$" + v.toLocaleString() }}, grid: {{ color: "#334155" }} }}
    }}
  }}
}});

// Savings rate
new Chart(document.getElementById("savings"), {{
  type: "bar",
  data: {{
    labels: {annual_labels},
    datasets: [{{ label: "Savings Rate %", data: {annual_savings},
                  backgroundColor: COLORS[0], borderRadius: 6 }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ labels: {{ color: "#e2e8f0" }} }} }},
    scales: {{
      x: {{ ticks: {{ color: "#94a3b8" }}, grid: {{ color: "#334155" }} }},
      y: {{ max: 100, ticks: {{ color: "#94a3b8", callback: v => v + "%" }}, grid: {{ color: "#334155" }} }}
    }}
  }}
}});

// Category donut
new Chart(document.getElementById("categories"), {{
  type: "doughnut",
  data: {{
    labels: {cat_labels},
    datasets: [{{ data: {cat_values}, backgroundColor: COLORS, borderWidth: 2, borderColor: "#1e293b" }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ position: "right", labels: {{ color: "#e2e8f0", font: {{ size: 11 }} }} }} }}
  }}
}});

// Annual income vs expense
new Chart(document.getElementById("annual"), {{
  type: "bar",
  data: {{
    labels: {annual_labels},
    datasets: [
      {{ label: "Income",  data: {annual_income},  backgroundColor: "#4ade8088", borderColor: "#4ade80", borderWidth: 1, borderRadius: 4 }},
      {{ label: "Expense", data: {annual_expense}, backgroundColor: "#f8717188", borderColor: "#f87171", borderWidth: 1, borderRadius: 4 }},
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ labels: {{ color: "#e2e8f0" }} }} }},
    scales: {{
      x: {{ ticks: {{ color: "#94a3b8" }}, grid: {{ color: "#334155" }} }},
      y: {{ ticks: {{ color: "#94a3b8", callback: v => "S$" + (v/1000).toFixed(0) + "k" }}, grid: {{ color: "#334155" }} }}
    }}
  }}
}});
</script>
</body>
</html>"""

    DASHBOARD.write_text(html, encoding="utf-8")
    print(f"  ✓  {DASHBOARD}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    if not INPUT_CSV.exists():
        print(f"❌  {INPUT_CSV} not found. Run 02_categorise.py first.")
        return

    print(f"  Loading {INPUT_CSV} ...")
    df = load()
    print(f"  {len(df):,} transactions | {df['year'].min()}–{df['year'].max()}")

    print("\n  Generating charts...")
    chart_monthly_cashflow(df)
    chart_annual_summary(df)
    chart_category_breakdown(df)
    chart_top_merchants(df)
    chart_spending_heatmap(df)
    chart_running_balance(df)

    print("\n  Generating text report...")
    report = generate_report(df)
    REPORT_TXT.write_text(report, encoding="utf-8")
    print(f"  ✓  {REPORT_TXT}")
    print(report)

    print("\n  Generating HTML dashboard...")
    generate_dashboard(df)

    print(f"\n{'─'*55}")
    print(f"  ✅  All done!")
    print(f"      {REPORT_TXT}          ← full text analysis")
    print(f"      {DASHBOARD}          ← open in browser for interactive charts")
    print(f"      {CHARTS_DIR}/                 ← PNG charts")
    print(f"{'─'*55}")


if __name__ == "__main__":
    main()