"""
RodPicks-US v1 — Monthly Price Momentum Strategy for US Stocks
===========================================================
120-stock universe blending S&P 500 + NASDAQ 100 across all sectors.
Scores on multi-timeframe momentum + ROE + FCF quality.
Selects top 5 each month.

Usage:
    python rodpicksus_v1.py                    # today's top-5 signal + dashboard
    python rodpicksus_v1.py --top 10           # top 10
    python rodpicksus_v1.py --backtest         # 2-year backtest
    python rodpicksus_v1.py --backtest --start 2024-01-01 --capital 25000
"""

import argparse
import json
import os
import warnings
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ── Universe: 120 stocks — S&P 500 + NASDAQ 100 blend across all sectors ─────
TICKERS = [
    # Technology (25)
    "AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "AVGO", "AMD",
    "ORCL", "CRM", "ADBE", "QCOM", "TXN", "INTC", "MU", "AMAT",
    "KLAC", "LRCX", "MRVL", "PANW", "SNOW", "CRWD", "FTNT", "NOW", "PLTR",

    # Consumer Discretionary (15)
    "TSLA", "HD", "MCD", "NKE", "SBUX", "TGT", "COST", "BKNG",
    "LOW", "ABNB", "UBER", "LYFT", "ETSY", "ROST", "YUM",

    # Financials (14)
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "AXP", "SPGI",
    "MCO", "CME", "ICE", "V", "MA", "PYPL",

    # Healthcare (15)
    "JNJ", "UNH", "LLY", "ABBV", "MRK", "PFE", "TMO", "DHR",
    "ABT", "BMY", "AMGN", "GILD", "ISRG", "VRTX", "REGN",

    # Industrials (12)
    "CAT", "HON", "UPS", "BA", "GE", "RTX", "LMT", "DE",
    "MMM", "EMR", "ETN", "NOC",

    # Communication Services (8)
    "NFLX", "DIS", "T", "VZ", "CMCSA", "TMUS", "EA", "WBD",

    # Energy (8)
    "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO",

    # Consumer Staples (8)
    "PG", "KO", "PEP", "WMT", "PM", "MO", "CL", "MDLZ",

    # Real Estate (5)
    "AMT", "PLD", "EQIX", "SPG", "O",

    # Materials (4)
    "LIN", "APD", "NEM", "FCX",

    # Utilities (3)
    "NEE", "DUK", "SO",
]

BENCHMARK   = "SPY"       # S&P 500 ETF as benchmark
MIN_PRICE   = 5.00        # exclude very cheap stocks
MAX_FCF_YIELD = 0.50
MIN_FACTORS = 2
COMMISSION  = 0.001       # 0.1% per trade (US brokers cheaper than SGX)

# ── Factor weights ────────────────────────────────────────────────────────────
WEIGHTS = {
    "mom_1m": 0.20,
    "mom_3m": 0.35,
    "mom_6m": 0.25,
    "roe":    0.10,
    "fcf":    0.10,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize(series: pd.Series) -> pd.Series:
    mn, mx = series.min(), series.max()
    if mx > mn:
        return (series - mn) / (mx - mn)
    return pd.Series([0.5] * len(series), index=series.index)


def momentum(prices: pd.DataFrame, ticker: str, days: int) -> float | None:
    if ticker not in prices.columns:
        return None
    col = prices[ticker].dropna()
    if len(col) < 5:
        return None
    cutoff = col.index[-1] - pd.Timedelta(days=days)
    past   = col[col.index <= cutoff]
    if past.empty:
        return None
    return float(col.iloc[-1] / past.iloc[-1]) - 1


def fetch_fundamentals(ticker: str) -> dict:
    try:
        info      = yf.Ticker(ticker).info
        mktcap    = info.get("marketCap")
        fcf       = info.get("freeCashflow")
        roe       = info.get("returnOnEquity")
        fcf_yield = (fcf / mktcap) if (fcf and mktcap and mktcap > 0) else None
        if fcf_yield is not None and abs(fcf_yield) > MAX_FCF_YIELD:
            fcf_yield = None
        if roe is not None and (roe < -1 or roe > 5):
            roe = None
        return {
            "name":      info.get("longName") or info.get("shortName") or ticker,
            "fcf_yield": fcf_yield,
            "roe":       roe,
        }
    except Exception:
        return {"name": ticker, "fcf_yield": None, "roe": None}


def fetch_prices(tickers: list, days: int = 200) -> pd.DataFrame:
    end   = date.today()
    start = end - timedelta(days=days)
    df = yf.download(
        tickers, start=start.isoformat(), end=end.isoformat(),
        auto_adjust=True, progress=False,
    )["Close"]
    if isinstance(df, pd.Series):
        df = df.to_frame()
    df.index = pd.to_datetime(df.index)
    return df


# ── Scoring ───────────────────────────────────────────────────────────────────

def build_scores(prices: pd.DataFrame, fundamentals: dict) -> pd.DataFrame:
    rows = []
    for ticker in TICKERS:
        if ticker not in prices.columns:
            continue
        col = prices[ticker].dropna()
        if col.empty:
            continue
        price = float(col.iloc[-1])
        if price < MIN_PRICE:
            continue

        fd  = fundamentals.get(ticker, {})
        m1  = momentum(prices, ticker, 30)
        m3  = momentum(prices, ticker, 90)
        m6  = momentum(prices, ticker, 180)
        roe = fd.get("roe")
        fcf = fd.get("fcf_yield")

        valid = sum(x is not None for x in [m1, m3, m6, roe, fcf])
        if valid < MIN_FACTORS:
            continue

        rows.append({
            "ticker":  ticker,
            "name":    fd.get("name", ticker),
            "price":   price,
            "mom_1m":  m1,
            "mom_3m":  m3,
            "mom_6m":  m6,
            "roe":     roe,
            "fcf":     fcf,
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).set_index("ticker")

    df["fcf_norm"] = normalize(df["fcf"].fillna(df["fcf"].median()))
    df["mom_1m_n"] = normalize(df["mom_1m"].fillna(df["mom_1m"].median()))
    df["mom_3m_n"] = normalize(df["mom_3m"].fillna(df["mom_3m"].median()))
    df["mom_6m_n"] = normalize(df["mom_6m"].fillna(df["mom_6m"].median()))
    df["roe_norm"] = normalize(df["roe"].fillna(df["roe"].median()))

    df["score"] = (
        df["mom_1m_n"] * WEIGHTS["mom_1m"] +
        df["mom_3m_n"] * WEIGHTS["mom_3m"] +
        df["mom_6m_n"] * WEIGHTS["mom_6m"] +
        df["roe_norm"] * WEIGHTS["roe"]    +
        df["fcf_norm"] * WEIGHTS["fcf"]
    )
    return df.sort_values("score", ascending=False)


# ── Signal ────────────────────────────────────────────────────────────────────

def run_signal(top_n: int = 5) -> pd.DataFrame:
    today = date.today().isoformat()
    print(f"\n{'='*58}")
    print(f"  RodPicks-US v1  |  Price Momentum  |  {today}")
    print(f"  120 stocks: S&P 500 + NASDAQ 100 blend")
    print(f"{'='*58}")
    print(f"\nFetching 6 months of prices for {len(TICKERS)} tickers...")
    prices = fetch_prices(TICKERS, days=200)

    print("Fetching fundamentals (ROE + FCF) — takes ~90s...")
    fundamentals = {t: fetch_fundamentals(t) for t in TICKERS}

    df = build_scores(prices, fundamentals)
    if df.empty:
        print("No eligible stocks. Check internet connection.")
        return pd.DataFrame()

    def print_block(df, n, label):
        print(f"\n{label}")
        print("-" * 58)
        for rank, (ticker, row) in enumerate(df.head(n).iterrows(), 1):
            m1 = f"{row['mom_1m']*100:+.1f}%"
            m3 = f"{row['mom_3m']*100:+.1f}%"
            m6 = f"{row['mom_6m']*100:+.1f}%"
            r  = f"{row['roe']*100:.1f}%"  if row['roe'] is not None else "N/A"
            f_ = f"{row['fcf']*100:+.1f}%" if row['fcf'] is not None else "N/A"
            print(f"  {rank}. {ticker:<6}  {row['name'][:24]:<24}  US${row['price']:.2f}  Score:{row['score']:.3f}")
            print(f"     1m:{m1:<7} 3m:{m3:<7} 6m:{m6:<7} ROE:{r:<7} FCF:{f_}")

    print_block(df, 5,  "TOP 5 PORTFOLIO")
    if top_n > 5:
        print_block(df, top_n, f"TOP {top_n}")

    picks = []
    for ticker, row in df.head(10).iterrows():
        picks.append({
            "rank":       int(df.index.get_loc(ticker)) + 1,
            "ticker":     ticker,
            "name":       row["name"],
            "price_usd":  round(row["price"], 4),
            "score":      round(row["score"], 4),
            "mom_1m_pct": round(row["mom_1m"] * 100, 2) if row["mom_1m"] is not None else None,
            "mom_3m_pct": round(row["mom_3m"] * 100, 2) if row["mom_3m"] is not None else None,
            "mom_6m_pct": round(row["mom_6m"] * 100, 2) if row["mom_6m"] is not None else None,
            "roe_pct":    round(row["roe"]    * 100, 2) if row["roe"]    is not None else None,
            "fcf_pct":    round(row["fcf"]    * 100, 2) if row["fcf"]    is not None else None,
        })

    out = {
        "date":         today,
        "generated_at": datetime.now().isoformat(),
        "market":       "US",
        "weights":      WEIGHTS,
        "top_10":       picks,
    }

    json_file = f"us_signal_output_{today}.json"
    with open(json_file, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n✅ Signal saved → {json_file}")

    history = _load_history()
    _append_history(history, out)
    generate_dashboard(out, history)
    print(f"✅ Dashboard saved → dashboard_us.html  (open in browser)")
    print(f"{'='*58}\n")
    return df


# ── History ───────────────────────────────────────────────────────────────────

HISTORY_FILE = "us_signal_history.json"

def _load_history() -> list:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return []

def _append_history(history: list, signal: dict):
    history = [h for h in history if h["date"] != signal["date"]]
    history.append({"date": signal["date"], "top_5": signal["top_10"][:5]})
    history.sort(key=lambda x: x["date"])
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


# ── Dashboard ─────────────────────────────────────────────────────────────────

def generate_dashboard(signal: dict, history: list):
    picks  = signal["top_10"][:5]
    today  = signal["date"]
    gen_at = signal["generated_at"][:16].replace("T", " ")

    hist_rows = ""
    for h in reversed(history[-12:]):
        top5 = ", ".join(p["ticker"] for p in h["top_5"])
        hist_rows += f"<tr><td>{h['date']}</td><td>{top5}</td></tr>\n"

    cards = ""
    for p in picks:
        m1  = f"{p['mom_1m_pct']:+.1f}%" if p["mom_1m_pct"] is not None else "N/A"
        m3  = f"{p['mom_3m_pct']:+.1f}%" if p["mom_3m_pct"] is not None else "N/A"
        m6  = f"{p['mom_6m_pct']:+.1f}%" if p["mom_6m_pct"] is not None else "N/A"
        roe = f"{p['roe_pct']:.1f}%"      if p["roe_pct"]   is not None else "N/A"
        fcf = f"{p['fcf_pct']:+.1f}%"     if p["fcf_pct"]   is not None else "N/A"
        score_pct = int(p["score"] * 100)
        cards += f"""
        <div class="card">
          <div class="rank">#{p['rank']}</div>
          <div class="ticker">{p['ticker']}</div>
          <div class="name">{p['name'][:28]}</div>
          <div class="price">US${p['price_usd']:.2f}</div>
          <div class="score-bar-wrap"><div class="score-bar" style="width:{score_pct}%"></div></div>
          <div class="score-label">Score: {p['score']:.3f}</div>
          <div class="factors">
            <span class="tag {'green' if p['mom_1m_pct'] and p['mom_1m_pct']>0 else 'red'}">1m {m1}</span>
            <span class="tag {'green' if p['mom_3m_pct'] and p['mom_3m_pct']>0 else 'red'}">3m {m3}</span>
            <span class="tag {'green' if p['mom_6m_pct'] and p['mom_6m_pct']>0 else 'red'}">6m {m6}</span>
            <span class="tag neutral">ROE {roe}</span>
            <span class="tag neutral">FCF {fcf}</span>
          </div>
          <div class="action">BUY — Equal weight (20% each)</div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RodPicks-US — US Monthly Signal</title>
<style>
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
          background:#0f1117; color:#e2e8f0; min-height:100vh; padding:24px; }}
  h1   {{ font-size:1.6rem; font-weight:700; color:#fff; }}
  .sub {{ color:#64748b; font-size:0.85rem; margin-top:4px; }}
  header {{ display:flex; justify-content:space-between; align-items:flex-start;
            border-bottom:1px solid #1e293b; padding-bottom:16px; margin-bottom:24px; }}
  .badge {{ background:#1a3a1a; color:#4ade80; padding:4px 10px;
            border-radius:99px; font-size:0.75rem; font-weight:600; }}
  .section-title {{ font-size:0.7rem; font-weight:700; letter-spacing:.1em;
                    text-transform:uppercase; color:#64748b; margin-bottom:12px; }}
  .weights {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:32px; }}
  .w-item  {{ background:#1e293b; border:1px solid #334155; border-radius:8px;
              padding:10px 14px; text-align:center; flex:1; min-width:80px; }}
  .w-label {{ font-size:0.65rem; color:#64748b; }}
  .w-val   {{ font-size:1rem; font-weight:700; color:#4ade80; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr));
            gap:16px; margin-bottom:32px; }}
  .card  {{ background:#1e293b; border-radius:12px; padding:18px; border:1px solid #334155; }}
  .rank  {{ font-size:0.7rem; color:#64748b; font-weight:600; }}
  .ticker{{ font-size:1.5rem; font-weight:800; color:#4ade80; margin:2px 0; }}
  .name  {{ font-size:0.75rem; color:#94a3b8; margin-bottom:8px;
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  .price {{ font-size:1.1rem; font-weight:700; color:#f1f5f9; margin-bottom:10px; }}
  .score-bar-wrap {{ background:#0f1117; border-radius:99px; height:6px; margin-bottom:4px; }}
  .score-bar {{ background:linear-gradient(90deg,#16a34a,#4ade80);
                border-radius:99px; height:6px; }}
  .score-label {{ font-size:0.7rem; color:#64748b; margin-bottom:10px; }}
  .factors {{ display:flex; flex-wrap:wrap; gap:4px; margin-bottom:12px; }}
  .tag {{ font-size:0.65rem; font-weight:700; padding:2px 7px; border-radius:99px; }}
  .green  {{ background:#14532d; color:#4ade80; }}
  .red    {{ background:#450a0a; color:#f87171; }}
  .neutral{{ background:#1a3a1a; color:#86efac; }}
  .action {{ font-size:0.7rem; font-weight:700; color:#4ade80;
             background:#1a2e05; padding:5px 10px; border-radius:6px; text-align:center; }}
  .note {{ background:#1e2d1e; border:1px solid #166534; border-radius:8px;
           padding:12px 16px; font-size:0.75rem; color:#86efac; margin-bottom:24px; }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ font-size:0.7rem; color:#64748b; text-align:left; padding:8px 12px;
        border-bottom:1px solid #1e293b; text-transform:uppercase; }}
  td {{ font-size:0.8rem; padding:8px 12px; border-bottom:1px solid #1e293b; color:#cbd5e1; }}
  tr:hover td {{ background:#1e293b; }}
  footer {{ color:#475569; font-size:0.7rem; margin-top:32px; }}
</style>
</head>
<body>
<header>
  <div>
    <h1>RodPicks-US v1 &nbsp; US Monthly Signal</h1>
    <p class="sub">S&P 500 + NASDAQ 100 Blend &nbsp;·&nbsp; Generated {gen_at}</p>
  </div>
  <span class="badge">Signal Date: {today}</span>
</header>
<div class="note">
  ⚠ &nbsp;Fundamental data (ROE, FCF) is current, not historical.
  Momentum is live from yfinance. Re-run on the <strong>1st trading day of each month.</strong>
  Not financial advice.
</div>
<p class="section-title">Factor Weights</p>
<div class="weights">
  <div class="w-item"><div class="w-label">1-Month Momentum</div><div class="w-val">20%</div></div>
  <div class="w-item"><div class="w-label">3-Month Momentum</div><div class="w-val">35%</div></div>
  <div class="w-item"><div class="w-label">6-Month Momentum</div><div class="w-val">25%</div></div>
  <div class="w-item"><div class="w-label">Return on Equity</div><div class="w-val">10%</div></div>
  <div class="w-item"><div class="w-label">FCF Yield</div><div class="w-val">10%</div></div>
</div>
<p class="section-title">This Month's Top 5 — Buy Equal Weight (20% each)</p>
<div class="cards">{cards}</div>
<p class="section-title">Pick History (last 12 months)</p>
<table>
  <thead><tr><th>Month</th><th>Top 5 Picks</th></tr></thead>
  <tbody>{hist_rows if hist_rows else '<tr><td colspan="2" style="color:#475569">Run the script each month to build history.</td></tr>'}</tbody>
</table>
<footer style="margin-top:24px">
  RodPicks-US v1 &nbsp;·&nbsp; US Price Strategy &nbsp;·&nbsp; 120 stocks &nbsp;·&nbsp;
  Data: yfinance &nbsp;·&nbsp; Not financial advice.
</footer>
</body>
</html>"""

    with open("dashboard_us.html", "w", encoding="utf-8") as f:
        f.write(html)


# ── Backtest ──────────────────────────────────────────────────────────────────

def next_month_start(d: date) -> date:
    return date(d.year + (d.month // 12), (d.month % 12) + 1, 1)


def run_backtest(start: str = None, capital: float = 25_000, top_n: int = 5):
    if start is None:
        start = (date.today() - timedelta(days=730)).isoformat()

    print(f"\n{'='*58}")
    print(f"  RodPicks-US v1 Backtest  {start} → {date.today()}")
    print(f"  Capital: US${capital:,.0f}  |  Top {top_n}  |  Commission: {COMMISSION*100:.2f}%/side")
    print(f"  Momentum (80%) IS historical. ROE+FCF (20%) use current data.")
    print(f"{'='*58}\n")

    buf_start   = (date.fromisoformat(start) - timedelta(days=200)).isoformat()
    all_tickers = list(set(TICKERS + [BENCHMARK]))
    print(f"Downloading price history ({buf_start} → today)...")
    raw = yf.download(all_tickers, start=buf_start, end=date.today().isoformat(),
                      auto_adjust=True, progress=False)["Close"]
    if isinstance(raw, pd.Series):
        raw = raw.to_frame()
    raw.index = pd.to_datetime(raw.index)

    print(f"Fetching fundamentals for {len(TICKERS)} stocks (~90s)...")
    fundamentals = {t: fetch_fundamentals(t) for t in TICKERS}

    def price_at(ticker, dt):
        if ticker not in raw.columns:
            return None
        col = raw[ticker].dropna()
        col = col[col.index <= pd.Timestamp(dt)]
        return float(col.iloc[-1]) if not col.empty else None

    rebalance_dates = []
    cur = date.fromisoformat(start).replace(day=1)
    while cur <= date.today():
        idx = raw.index[(raw.index.month == cur.month) & (raw.index.year == cur.year)]
        if not idx.empty:
            rebalance_dates.append(idx[0].date())
        cur = next_month_start(cur)

    print(f"Simulating {len(rebalance_dates)} monthly rebalances...\n")
    print(f"  {'Date':<12} {'Picks':<35} {'Ret':>6}  {'Portfolio':>11}  {'S&P 500':>11}")
    print(f"  {'-'*12} {'-'*35} {'-'*6}  {'-'*11}  {'-'*11}")

    portfolio = capital
    bm_units  = None
    bm_value  = capital
    monthly_rets = []
    history = []

    for i, reb in enumerate(rebalance_dates):
        hist_prices = raw[raw.index <= pd.Timestamp(reb)]
        df = build_scores(hist_prices, fundamentals)
        if df.empty:
            continue

        picks = df.head(top_n).index.tolist()
        entry = {t: price_at(t, reb) for t in picks}
        entry = {t: p for t, p in entry.items() if p}
        if not entry:
            continue

        exit_date = rebalance_dates[i+1] if i+1 < len(rebalance_dates) else date.today()
        exit_p    = {t: price_at(t, exit_date) for t in entry}
        exit_p    = {t: p for t, p in exit_p.items() if p}

        rets = [exit_p[t]/entry[t]-1 for t in entry if t in exit_p and entry[t]>0]
        if not rets:
            continue

        avg = float(np.mean(rets))
        portfolio *= (1 - COMMISSION * len(entry))
        portfolio *= (1 + avg)
        portfolio *= (1 - COMMISSION * len(exit_p))
        monthly_rets.append(avg)

        bm_e = price_at(BENCHMARK, reb)
        bm_x = price_at(BENCHMARK, exit_date)
        if bm_units is None and bm_e:
            bm_units = capital / bm_e
        if bm_units and bm_x:
            bm_value = bm_units * bm_x

        pick_str = " ".join(t for t in picks[:5])
        print(f"  {reb}  {pick_str:<35} {avg*100:>+5.1f}%  US${portfolio:>9,.0f}  US${bm_value:>9,.0f}")
        history.append({
            "date": reb.isoformat(),
            "picks": picks,
            "return_pct": round(avg*100, 2),
            "portfolio": round(portfolio, 2),
            "benchmark": round(bm_value, 2),
        })

    n_yr   = (date.today() - date.fromisoformat(start)).days / 365.25
    tot    = (portfolio/capital - 1)*100
    bm_tot = (bm_value/capital  - 1)*100
    cagr   = ((portfolio/capital)**(1/n_yr)-1)*100 if n_yr>0 else 0
    bm_cagr= ((bm_value/capital)**(1/n_yr)-1)*100 if n_yr>0 else 0
    sharpe = (np.mean(monthly_rets)/np.std(monthly_rets)*np.sqrt(12)
              if len(monthly_rets)>1 else 0)

    print(f"\n{'='*58}")
    print(f"  RESULTS  ({start} → {date.today()})")
    print(f"{'='*58}")
    print(f"  Strategy  Total:{tot:+.1f}%  CAGR:{cagr:.1f}%  Sharpe:{sharpe:.2f}")
    print(f"  S&P 500   Total:{bm_tot:+.1f}%  CAGR:{bm_cagr:.1f}%")
    print(f"  Alpha:    {tot-bm_tot:+.1f}pp")
    print(f"  Months:   {len(monthly_rets)}")
    print(f"{'='*58}\n")

    fname = f"us_backtest_{start}_{date.today().isoformat()}.json"
    with open(fname, "w") as f:
        json.dump({
            "start": start, "end": date.today().isoformat(),
            "capital": capital, "top_n": top_n,
            "total_return_pct": round(tot,2),
            "cagr_pct": round(cagr,2),
            "sharpe": round(sharpe,2),
            "benchmark_return_pct": round(bm_tot,2),
            "benchmark_cagr_pct": round(bm_cagr,2),
            "alpha_pp": round(tot-bm_tot,2),
            "history": history,
        }, f, indent=2)
    print(f"✅ Backtest saved → {fname}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RodPicks-US v1 — US Price Momentum Strategy")
    parser.add_argument("--top",      type=int,   default=5,      help="Number of picks (default 5)")
    parser.add_argument("--backtest", action="store_true",        help="Run historical backtest")
    parser.add_argument("--start",    type=str,   default=None,   help="Backtest start YYYY-MM-DD")
    parser.add_argument("--capital",  type=float, default=25_000, help="Starting capital USD (default 25000)")
    args = parser.parse_args()

    if args.backtest:
        run_backtest(start=args.start, capital=args.capital, top_n=args.top)
    else:
        run_signal(top_n=args.top)
