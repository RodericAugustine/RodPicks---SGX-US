"""
RodPicks 3-Month Backtest — Jun 2025 to Aug 2025
=============================================
Starting capital: SGD S$35,000 (SGX) + USD US$40,000 (US)
SGX lot size: floor to nearest 100 shares per stock
Tracks monthly P&L, margin usage, and cumulative summary.

Run: python backtest_jun25.py
"""

import math, json, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import date, timedelta

# ── Config ────────────────────────────────────────────────────────────────────
SGX_START    = 40_000.0   # S$ starting capital
US_START     = 40_000.0   # US$ starting capital
SGX_ALLOC    = SGX_START / 3   # S$11,666.67 per SGX stock
US_ALLOC     = US_START  / 5   # US$8,000 per US stock
SGX_COMM     = 0.002           # 0.2% per side
US_COMM      = 0.001           # 0.1% per side
LOT          = 100             # SGX lot size (always floor to nearest 100)
SGD_USD_RATE = 0.74            # approx, for combined summary only

MONTHS = [
    ("2025-06-01", "2025-06-30"),
    ("2025-07-01", "2025-07-31"),
    ("2025-08-01", "2025-08-31"),
]

SGX_TICKERS = [
    "D05.SI","O39.SI","U11.SI","Z74.SI","C6L.SI","S58.SI","V03.SI",
    "G13.SI","BN4.SI","C07.SI","BS6.SI","A17U.SI","C52.SI","J36.SI",
    "S63.SI","F34.SI","N2IU.SI","ME8U.SI","K71U.SI","T82U.SI","U96.SI",
    "9CI.SI","CC3.SI","H78.SI","U14.SI","S68.SI","C38U.SI","D01.SI","Y92.SI",
    "Q0F.SI","AWX.SI","5E2.SI","OV8.SI","U10.SI",
    "AJBU.SI","BUOU.SI","HMN.SI","F9D.SI","M44U.SI",
]

US_TICKERS = [
    "AAPL","MSFT","NVDA","META","GOOGL","AMZN","AVGO","AMD",
    "ORCL","CRM","ADBE","QCOM","TXN","INTC","MU","AMAT",
    "KLAC","LRCX","MRVL","PANW","SNOW","CRWD","FTNT","NOW","PLTR",
    "TSLA","HD","MCD","NKE","SBUX","TGT","COST","BKNG",
    "LOW","ABNB","UBER","LYFT","ETSY","ROST","YUM",
    "JPM","BAC","WFC","GS","MS","BLK","AXP","SPGI",
    "MCO","CME","ICE","V","MA","PYPL",
    "JNJ","UNH","LLY","ABBV","MRK","PFE","TMO","DHR",
    "ABT","BMY","AMGN","GILD","ISRG","VRTX","REGN",
    "CAT","HON","UPS","BA","GE","RTX","LMT","DE","MMM","EMR","ETN","NOC",
    "NFLX","DIS","T","VZ","CMCSA","TMUS","EA","WBD",
    "XOM","CVX","COP","SLB","EOG","MPC","PSX","VLO",
    "PG","KO","PEP","WMT","PM","MO","CL","MDLZ",
    "AMT","PLD","EQIX","SPG","O",
    "LIN","APD","NEM","FCX","NEE","DUK","SO",
]


# ── Scoring helpers ───────────────────────────────────────────────────────────

def normalize(s):
    mn, mx = s.min(), s.max()
    return (s - mn)/(mx - mn) if mx > mn else pd.Series([0.5]*len(s), index=s.index)

def momentum(prices, ticker, days):
    if ticker not in prices.columns: return None
    col = prices[ticker].dropna()
    if len(col) < 5: return None
    past = col[col.index <= col.index[-1] - pd.Timedelta(days=days)]
    return float(col.iloc[-1]/past.iloc[-1]) - 1 if not past.empty else None

def fetch_fund(ticker):
    try:
        info = yf.Ticker(ticker).info
        mc = info.get("marketCap"); fcf = info.get("freeCashflow"); roe = info.get("returnOnEquity")
        fy = (fcf/mc) if (fcf and mc and mc > 0) else None
        if fy  is not None and abs(fy)  > 0.5: fy  = None
        if roe is not None and (roe < -1 or roe > 5): roe = None
        return {"name": info.get("longName") or ticker, "fcf": fy, "roe": roe}
    except:
        return {"name": ticker, "fcf": None, "roe": None}

def score_stocks(tickers, prices, fund, top_n):
    rows = []
    for t in tickers:
        if t not in prices.columns: continue
        col = prices[t].dropna()
        if col.empty or float(col.iloc[-1]) < 0.10: continue
        fd = fund.get(t, {})
        m1 = momentum(prices, t, 30)
        m3 = momentum(prices, t, 90)
        m6 = momentum(prices, t, 180)
        roe = fd.get("roe"); fcf = fd.get("fcf")
        if sum(x is not None for x in [m1, m3, m6, roe, fcf]) < 2: continue
        rows.append({"ticker": t, "name": fd.get("name", t), "price": float(col.iloc[-1]),
                     "m1": m1, "m3": m3, "m6": m6, "roe": roe, "fcf": fcf})
    if not rows: return []
    df = pd.DataFrame(rows).set_index("ticker")
    for c in ["m1","m3","m6","roe","fcf"]: df[c] = df[c].fillna(df[c].median())
    df["score"] = (normalize(df["m1"])*0.30 + normalize(df["m3"])*0.25 +
                   normalize(df["m6"])*0.25 + normalize(df["roe"])*0.10 +
                   normalize(df["fcf"])*0.10)
    return df.sort_values("score", ascending=False).head(top_n)[["name","price","score"]].to_dict("index")


# ── Download data ─────────────────────────────────────────────────────────────

print("\nDownloading historical price data (this may take ~30 seconds)...")
# Need from Dec 2024 to cover 6-month lookback for Jun 2025 scoring
all_tickers = SGX_TICKERS + US_TICKERS + ["ES3.SI", "SPY"]
raw = yf.download(all_tickers, start="2024-12-01", end="2025-09-02",
                  auto_adjust=True, progress=False)["Close"]
if isinstance(raw, pd.Series): raw = raw.to_frame()
raw.index = pd.to_datetime(raw.index)
print("Done.\n")

print("Fetching fundamentals (once for all months)...")
sgx_fund = {t: fetch_fund(t) for t in SGX_TICKERS}
us_fund  = {t: fetch_fund(t) for t in US_TICKERS}
print("Done.\n")

def price_at(ticker, d):
    if ticker not in raw.columns: return None
    col = raw[ticker].dropna()
    col = col[col.index <= pd.Timestamp(d)]
    return float(col.iloc[-1]) if not col.empty else None


# ── Run monthly backtests ─────────────────────────────────────────────────────

sgx_cash = SGX_START
us_cash  = US_START
monthly  = []

for start_str, end_str in MONTHS:
    start = date.fromisoformat(start_str)
    end   = date.fromisoformat(end_str)

    hist      = raw[raw.index <= pd.Timestamp(start)]
    sgx_picks = score_stocks(SGX_TICKERS, hist, sgx_fund, 3)
    us_picks  = score_stocks(US_TICKERS,  hist, us_fund,  5)

    # ── SGX ──
    sgx_res = []
    for ticker, d in sgx_picks.items():
        buy_p  = price_at(ticker, start)
        sell_p = price_at(ticker, end)
        if not buy_p or not sell_p: continue
        # Floor to nearest lot of 100 shares — never over-allocate
        shares    = max(math.floor(SGX_ALLOC / buy_p / LOT) * LOT, LOT)
        value_in  = shares * buy_p
        value_out = shares * sell_p
        comm_buy  = value_in  * SGX_COMM
        comm_sell = value_out * SGX_COMM
        gross     = value_out - value_in
        net       = gross - comm_buy - comm_sell
        idle      = SGX_ALLOC - value_in   # cash not deployed due to lot rounding
        sgx_res.append({
            "ticker": ticker.replace(".SI",""), "name": d["name"][:24],
            "shares": shares, "buy": buy_p, "sell": sell_p,
            "gross": gross, "comm": comm_buy+comm_sell,
            "net": net, "ret": net/value_in*100, "idle": idle
        })

    sgx_invested = sum(r["shares"]*r["buy"] for r in sgx_res)
    sgx_comm_tot = sum(r["comm"] for r in sgx_res)
    sgx_margin   = max(0.0, sgx_invested - sgx_cash)
    sgx_net      = sum(r["net"] for r in sgx_res)
    sgx_cash_end = sgx_cash + sgx_net

    # ── US ──
    us_res = []
    for ticker, d in us_picks.items():
        buy_p  = price_at(ticker, start)
        sell_p = price_at(ticker, end)
        if not buy_p or not sell_p: continue
        shares    = max(math.floor(US_ALLOC / buy_p), 1)
        value_in  = shares * buy_p
        value_out = shares * sell_p
        comm_buy  = value_in  * US_COMM
        comm_sell = value_out * US_COMM
        gross     = value_out - value_in
        net       = gross - comm_buy - comm_sell
        us_res.append({
            "ticker": ticker, "name": d["name"][:24],
            "shares": shares, "buy": buy_p, "sell": sell_p,
            "gross": gross, "comm": comm_buy+comm_sell,
            "net": net, "ret": net/value_in*100
        })

    us_invested  = sum(r["shares"]*r["buy"] for r in us_res)
    us_comm_tot  = sum(r["comm"] for r in us_res)
    us_margin    = max(0.0, us_invested - us_cash)
    us_net       = sum(r["net"] for r in us_res)
    us_cash_end  = us_cash + us_net

    # Benchmarks
    sti_buy = price_at("ES3.SI", start); sti_sell = price_at("ES3.SI", end)
    spy_buy = price_at("SPY",    start); spy_sell = price_at("SPY",    end)
    sti_ret = (sti_sell/sti_buy - 1)*100 if sti_buy and sti_sell else 0
    spy_ret = (spy_sell/spy_buy - 1)*100 if spy_buy and spy_sell else 0

    monthly.append({
        "period": f"{start_str} → {end_str}",
        "sgx_cash_start": sgx_cash, "us_cash_start": us_cash,
        "sgx_invested": sgx_invested, "us_invested": us_invested,
        "sgx_margin": sgx_margin, "us_margin": us_margin,
        "sgx_picks": sgx_res, "us_picks": us_res,
        "sgx_net": sgx_net, "us_net": us_net,
        "sgx_comm": sgx_comm_tot, "us_comm": us_comm_tot,
        "sgx_cash_end": sgx_cash_end, "us_cash_end": us_cash_end,
        "sti_ret": sti_ret, "spy_ret": spy_ret,
    })

    sgx_cash = sgx_cash_end
    us_cash  = us_cash_end


# ── Print results ─────────────────────────────────────────────────────────────

SEP  = "=" * 72
SEP2 = "─" * 72

print(SEP)
print("  RodPicks BACKTEST — JUN 2025 to AUG 2025  (updated allocation)")
print(f"  SGX Capital: S${SGX_START:,.0f} (S${SGX_ALLOC:,.2f}/stock, floor to nearest 100 shares)")
print(f"  US  Capital: US${US_START:,.0f} (US${US_ALLOC:,.2f}/stock)")
print(SEP)

for i, m in enumerate(monthly, 1):
    print(f"\n  MONTH {i}: {m['period']}")
    print(f"  {SEP2}")
    print(f"  Starting cash : SGD S${m['sgx_cash_start']:>10,.2f}  |  USD US${m['us_cash_start']:>10,.2f}")

    print(f"\n  SGX — Top 3 Picks  (S${SGX_ALLOC:,.2f} each, lot size 100)")
    print(f"  {'Ticker':<8} {'Name':<25} {'Lots':>4} {'Shares':>6}  {'Buy':>7}  {'Sell':>7}  {'Invested':>10}  {'Net P&L':>10}  {'Ret%':>6}  {'Idle':>7}")
    print(f"  {'─'*8} {'─'*25} {'─'*4} {'─'*6}  {'─'*7}  {'─'*7}  {'─'*10}  {'─'*10}  {'─'*6}  {'─'*7}")
    for r in m['sgx_picks']:
        sign = "+" if r['net'] >= 0 else ""
        lots = r['shares'] // 100
        invested = r['shares'] * r['buy']
        print(f"  {r['ticker']:<8} {r['name']:<25} {lots:>4} {r['shares']:>6}  "
              f"S${r['buy']:>5.3f}  S${r['sell']:>5.3f}  "
              f"S${invested:>8,.2f}  {sign}S${r['net']:>7,.2f}  {sign}{r['ret']:>5.2f}%  S${r['idle']:>5.2f}")

    sgx_sign = "+" if m['sgx_net'] >= 0 else ""
    print(f"\n  SGX Total Invested : S${m['sgx_invested']:>10,.2f}  (of S${SGX_START:,.2f} available)")
    print(f"  SGX Commission     : S${m['sgx_comm']:>10,.2f}")
    print(f"  SGX Net P&L        : {sgx_sign}S${m['sgx_net']:>9,.2f}  ({sgx_sign}{m['sgx_net']/SGX_START*100:.2f}% on S${SGX_START:,.0f})")
    if m['sgx_margin'] > 0:
        print(f"  ⚠  MARGIN NEEDED   : S${m['sgx_margin']:,.2f}")
    else:
        print(f"  ✅ No margin needed")

    print(f"\n  US — Top 5 Picks   (US${US_ALLOC:,.2f} each)")
    print(f"  {'Ticker':<8} {'Name':<25} {'Shares':>6}  {'Buy':>8}  {'Sell':>8}  {'Invested':>11}  {'Net P&L':>11}  {'Ret%':>6}")
    print(f"  {'─'*8} {'─'*25} {'─'*6}  {'─'*8}  {'─'*8}  {'─'*11}  {'─'*11}  {'─'*6}")
    for r in m['us_picks']:
        sign = "+" if r['net'] >= 0 else ""
        invested = r['shares'] * r['buy']
        print(f"  {r['ticker']:<8} {r['name']:<25} {r['shares']:>6}  "
              f"US${r['buy']:>6.2f}  US${r['sell']:>6.2f}  "
              f"US${invested:>8,.2f}  {sign}US${r['net']:>8,.2f}  {sign}{r['ret']:>5.2f}%")

    us_sign = "+" if m['us_net'] >= 0 else ""
    print(f"\n  US  Total Invested : US${m['us_invested']:>10,.2f}  (of US${US_START:,.2f} available)")
    print(f"  US  Commission     : US${m['us_comm']:>10,.2f}")
    print(f"  US  Net P&L        : {us_sign}US${m['us_net']:>9,.2f}  ({us_sign}{m['us_net']/US_START*100:.2f}% on US${US_START:,.0f})")
    if m['us_margin'] > 0:
        print(f"  ⚠  MARGIN NEEDED   : US${m['us_margin']:,.2f}")
    else:
        print(f"  ✅ No margin needed")

    combined_sgd = m['sgx_net'] + m['us_net'] / SGD_USD_RATE
    print(f"\n  Benchmark  : STI ETF {m['sti_ret']:+.2f}%  |  S&P 500 {m['spy_ret']:+.2f}%")
    print(f"  Combined P&L (SGD equiv) : S${combined_sgd:+,.2f}")
    print(f"  Capital end  : SGD S${m['sgx_cash_end']:,.2f}  |  USD US${m['us_cash_end']:,.2f}")

# Cumulative summary
print(f"\n{SEP}")
print("  3-MONTH CUMULATIVE SUMMARY  (Jun–Aug 2025)")
print(SEP)
total_sgx      = sum(m['sgx_net']  for m in monthly)
total_us       = sum(m['us_net']   for m in monthly)
total_sgx_comm = sum(m['sgx_comm'] for m in monthly)
total_us_comm  = sum(m['us_comm']  for m in monthly)
total_comb_sgd = total_sgx + total_us / SGD_USD_RATE
total_inv_sgd  = SGX_START + US_START / SGD_USD_RATE
sgx_end        = monthly[-1]['sgx_cash_end']
us_end         = monthly[-1]['us_cash_end']

print(f"  Starting capital   : SGD S${SGX_START:>10,.2f}  +  USD US${US_START:>10,.2f}")
print(f"  Ending capital     : SGD S${sgx_end:>10,.2f}  +  USD US${us_end:>10,.2f}")
print()
print(f"  SGX total P&L      :  S${total_sgx:>+10,.2f}  ({total_sgx/SGX_START*100:+.2f}% on S${SGX_START:,.0f})")
print(f"  US  total P&L      : US${total_us:>+10,.2f}  ({total_us/US_START*100:+.2f}% on US${US_START:,.0f})")
print(f"  SGX total commission:  S${total_sgx_comm:>9,.2f}")
print(f"  US  total commission: US${total_us_comm:>8,.2f}")
print(f"  Combined net (SGD) :  S${total_comb_sgd:>+10,.2f}  ({total_comb_sgd/total_inv_sgd*100:+.2f}% on combined capital)")
print()

any_margin = any(m['sgx_margin'] > 0 or m['us_margin'] > 0 for m in monthly)
if any_margin:
    print("  MARGIN USAGE:")
    for i, m in enumerate(monthly, 1):
        if m['sgx_margin'] > 0:
            print(f"    Month {i} SGX: S${m['sgx_margin']:,.2f} margin used")
        if m['us_margin'] > 0:
            print(f"    Month {i} US:  US${m['us_margin']:,.2f} margin used")
else:
    print("  ✅ MARGIN: Never needed across all 3 months")

print(SEP)

# Save results
with open("backtest_jun25_aug25.json", "w") as f:
    json.dump(monthly, f, indent=2, default=str)
print("✅ Results saved → backtest_jun25_aug25.json\n")
