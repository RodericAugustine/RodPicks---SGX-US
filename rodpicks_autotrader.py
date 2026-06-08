"""
RodPicks AutoTrader — Full Automated Monthly Trading System
========================================================
Rebalances on the 1st of each month: sells existing positions then buys new picks.
SGX rebalances at 9:05am SGT (market open). US rebalances at 9:35pm SGT (US market open).
If 1st falls on weekend or public holiday, shifts to next trading day.

Capital:
  SGX: S$<YOUR_SGX_CAPITAL> — top 3 picks
  US:  US$<YOUR_US_CAPITAL> — top 5 picks

Margin: always executes; notifies if shortfall exists.

Usage:
  python rodpicks_autotrader.py --rebalance --market SGX      # rebalance SGX only
  python rodpicks_autotrader.py --rebalance --market US       # rebalance US only
  python rodpicks_autotrader.py --rebalance --dry             # preview both, no orders
  python rodpicks_autotrader.py --status                      # show current holdings
  python rodpicks_autotrader.py --backtest --start 2026-01-01 --end 2026-01-31
"""

import argparse
import ctypes
import json
import math
import os
import winsound
import warnings
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ── Config ────────────────────────────────────────────────────────────────────
OPEND_HOST      = "127.0.0.1"
OPEND_PORT      = 11111
SGX_CAPITAL     = 40_000     # TODO: set your SGX capital (S$)
US_CAPITAL      = 40_000     # TODO: set your US capital (US$)
SGX_COMMISSION  = 0.002      # 0.2% per side
US_COMMISSION   = 0.001      # 0.1% per side
MARGIN_BUFFER   = 0.10       # allow up to 10% shortfall on margin
LOT_SIZE        = 100        # SGX lot size
SGD_USD_RATE    = 0.74       # approx rate for display only
SGT             = timezone(timedelta(hours=8))
TRADE_LOG       = "autotrader_log.json"

# SGX public holidays 2026 (add more as needed)
SGX_HOLIDAYS = {
    date(2026, 1, 1),   # New Year
    date(2026, 1, 29),  # CNY
    date(2026, 1, 30),  # CNY
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 1),   # Labour Day
    date(2026, 5, 11),  # Vesak Day
    date(2026, 8, 10),  # Hari Raya Haji
    date(2026, 8, 9),   # National Day
    date(2026, 10, 20), # Deepavali
    date(2026, 12, 25), # Christmas
}

# US market holidays 2026
US_HOLIDAYS = {
    date(2026, 1, 1),   # New Year
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 4),   # Independence Day (observed Jul 3)
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving
    date(2026, 12, 25), # Christmas
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def notify(title, msg):
    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    ctypes.windll.user32.MessageBoxW(0, msg, title, 0x40 | 0x40000)

def next_trading_day(d: date, holidays: set) -> date:
    """Return d if it's a trading day, else shift forward to next."""
    while d.weekday() >= 5 or d in holidays:
        d += timedelta(days=1)
    return d

def get_open_date(ref_date: date = None) -> date:
    """1st of current month, shifted if weekend/holiday."""
    d = (ref_date or date.today()).replace(day=1)
    return next_trading_day(d, SGX_HOLIDAYS)

def get_close_date(open_date: date) -> date:
    """1st trading day of the month after open_date — the next rebalance date."""
    if open_date.month == 12:
        d = date(open_date.year + 1, 1, 1)
    else:
        d = date(open_date.year, open_date.month + 1, 1)
    return next_trading_day(d, SGX_HOLIDAYS)

def sgx_futu(t): return f"SG.{t.replace('.SI','').replace('SG.','')}"
def us_futu(t):  return f"US.{t.replace('US.','')}"
def short(c):    return c.replace("SG.","").replace("US.","")

def calc_lots(capital, price):
    lots = math.floor(capital / price / LOT_SIZE)
    return max(lots * LOT_SIZE, LOT_SIZE)

def calc_shares(capital, price):
    return max(math.floor(capital / price), 1)

def load_log():
    return json.load(open(TRADE_LOG)) if os.path.exists(TRADE_LOG) else {"open": [], "history": []}

def save_log(log):
    with open(TRADE_LOG, "w") as f:
        json.dump(log, f, indent=2)


# ── Moomoo connection ─────────────────────────────────────────────────────────

def get_moomoo(market):
    from futu import OpenQuoteContext, OpenSecTradeContext, TrdMarket, SecurityFirm
    mkts = {"SG": TrdMarket.SG, "US": TrdMarket.US}
    q = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
    t = OpenSecTradeContext(filter_trdmarket=mkts[market],
                            host=OPEND_HOST, port=OPEND_PORT,
                            security_firm=SecurityFirm.FUTUSG)
    return q, t

def get_acc(t):
    from futu import TrdEnv
    ret, lst = t.get_acc_list()
    if ret != 0: return None
    p = lst[lst["trd_env"] == TrdEnv.REAL]
    return int(p.iloc[0]["acc_id"]) if not p.empty else None

def get_cash(t, acc):
    """Returns USD cash balance (us_cash field).
    Account base currency is HKD but all trading capital is held in USD.
    SGX trades auto-convert USD→SGD at execution.
    """
    ret, info = t.accinfo_query(trd_env=__import__("futu").TrdEnv.REAL, acc_id=acc)
    if ret != 0: return 0
    # Prefer us_cash (explicit USD wallet); fall back to cash if not present
    if "us_cash" in info.columns:
        return float(info["us_cash"].iloc[0])
    return float(info["cash"].iloc[0])

def get_price_live(q, code):
    ret, s = q.get_market_snapshot([code])
    if ret != 0 or s.empty: return None
    p = s["last_price"].iloc[0] or s["prev_close_price"].iloc[0]
    return float(p) if p else None

def place(t, acc, code, side, price, qty, market):
    from futu import TrdSide, OrderType, TrdEnv
    mult = 1.01 if side == TrdSide.BUY else 0.99
    dp   = 3 if market == "SG" else 2
    ret, data = t.place_order(
        price=round(price * mult, dp), qty=qty, code=code,
        trd_side=side, order_type=OrderType.NORMAL,
        trd_env=TrdEnv.REAL, acc_id=acc
    )
    return (ret == 0, data["order_id"].iloc[0] if ret == 0 else str(data))


# ── Scoring (reused from signal scripts) ──────────────────────────────────────

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
    "LIN","APD","NEM","FCX",
    "NEE","DUK","SO",
]

def normalize(s):
    mn, mx = s.min(), s.max()
    return (s - mn) / (mx - mn) if mx > mn else pd.Series([0.5]*len(s), index=s.index)

def momentum(prices, ticker, days):
    if ticker not in prices.columns: return None
    col = prices[ticker].dropna()
    if len(col) < 5: return None
    past = col[col.index <= col.index[-1] - pd.Timedelta(days=days)]
    return float(col.iloc[-1] / past.iloc[-1]) - 1 if not past.empty else None

def fetch_fundamentals(ticker):
    try:
        info = yf.Ticker(ticker).info
        mc   = info.get("marketCap")
        fcf  = info.get("freeCashflow")
        roe  = info.get("returnOnEquity")
        fy   = (fcf/mc) if (fcf and mc and mc>0) else None
        if fy  is not None and abs(fy)  > 0.5: fy  = None
        if roe is not None and (roe<-1 or roe>5): roe = None
        return {"name": info.get("longName") or ticker, "fcf": fy, "roe": roe}
    except:
        return {"name": ticker, "fcf": None, "roe": None}

def score_stocks(tickers, prices, fundamentals, top_n):
    rows = []
    for t in tickers:
        if t not in prices.columns: continue
        col = prices[t].dropna()
        if col.empty or float(col.iloc[-1]) < 0.10: continue
        fd  = fundamentals.get(t, {})
        m1  = momentum(prices, t, 30)
        m3  = momentum(prices, t, 90)
        m6  = momentum(prices, t, 180)
        roe = fd.get("roe")
        fcf = fd.get("fcf")
        if sum(x is not None for x in [m1,m3,m6,roe,fcf]) < 2: continue
        rows.append({"ticker":t,"name":fd.get("name",t),
                     "price":float(col.iloc[-1]),
                     "m1":m1,"m3":m3,"m6":m6,"roe":roe,"fcf":fcf})
    if not rows: return []
    df = pd.DataFrame(rows).set_index("ticker")
    for c in ["m1","m3","m6","roe","fcf"]:
        df[c] = df[c].fillna(df[c].median())
    df["score"] = (
        normalize(df["m1"]) * 0.20 +
        normalize(df["m3"]) * 0.35 +
        normalize(df["m6"]) * 0.25 +
        normalize(df["roe"])* 0.10 +
        normalize(df["fcf"])* 0.10
    )
    df = df.sort_values("score", ascending=False)
    return df.head(top_n)[["name","price","m1","m3","m6","roe","fcf","score"]].to_dict("index")


# ── Open positions ────────────────────────────────────────────────────────────

def open_positions(dry_run=False, market="BOTH"):
    today    = date.today()
    open_dt  = get_open_date(today)
    close_dt = get_close_date(open_dt)
    now_str  = datetime.now(SGT).strftime("%Y-%m-%d %H:%M:%S SGT")
    mode     = "DRY RUN" if dry_run else "PAPER TRADE"

    print(f"\n{'='*62}")
    print(f"  RodPicks AutoTrader — OPEN [{mode}] [{market}]")
    print(f"  {now_str}")
    print(f"  Open date : {open_dt}  |  Next rebalance: {close_dt}")
    print(f"{'='*62}\n")

    # Generate picks
    print("Fetching prices and scoring stocks...")
    sgx_prices = yf.download(SGX_TICKERS, start=(today-timedelta(days=200)).isoformat(),
                              end=today.isoformat(), auto_adjust=True, progress=False)["Close"]
    us_prices  = yf.download(US_TICKERS,  start=(today-timedelta(days=200)).isoformat(),
                              end=today.isoformat(), auto_adjust=True, progress=False)["Close"]
    if isinstance(sgx_prices, pd.Series): sgx_prices = sgx_prices.to_frame()
    if isinstance(us_prices,  pd.Series): us_prices  = us_prices.to_frame()
    sgx_prices.index = pd.to_datetime(sgx_prices.index)
    us_prices.index  = pd.to_datetime(us_prices.index)

    print("Fetching fundamentals...")
    sgx_fund = {t: fetch_fundamentals(t) for t in SGX_TICKERS}
    us_fund  = {t: fetch_fundamentals(t) for t in US_TICKERS}

    sgx_picks = score_stocks(SGX_TICKERS, sgx_prices, sgx_fund, 3)
    us_picks  = score_stocks(US_TICKERS,  us_prices,  us_fund,  5)

    print(f"\n  TOP 3 SGX PICKS:")
    for t, d in sgx_picks.items():
        print(f"    {t.replace('.SI',''):<6} {d['name'][:28]:<28} S${d['price']:.3f}  Score:{d['score']:.3f}")
    print(f"\n  TOP 5 US PICKS:")
    for t, d in us_picks.items():
        print(f"    {t:<6} {d['name'][:28]:<28} US${d['price']:.2f}  Score:{d['score']:.3f}")

    trades = []

    # ── SGX ──────────────────────────────────────────────────────────────────
    if market in ("SGX", "BOTH"):
        print(f"\n{'─'*62}")
        print(f"  SGX — Balance Check (S${SGX_CAPITAL:,.0f} SGD, funded via USD auto-conversion)")
        print(f"{'─'*62}")
        try:
            q_sg, t_sg = get_moomoo("SG")
            acc_sg     = get_acc(t_sg)
            cash_usd   = get_cash(t_sg, acc_sg) if acc_sg else 0
            # SGX capital required in USD terms (S$35,000 ÷ SGD_USD_RATE)
            sgx_required_usd = SGX_CAPITAL * SGD_USD_RATE
            shortfall  = max(0, sgx_required_usd - cash_usd)

            print(f"  USD balance  : US${cash_usd:>9,.2f}  (auto-converts to SGD at execution)")
            print(f"  Required     : US${sgx_required_usd:>9,.2f}  (≈ S${SGX_CAPITAL:,.0f} at rate {SGD_USD_RATE})")
            if shortfall == 0:
                print(f"  ✅ Sufficient USD — SGD will be auto-converted at execution")
            else:
                print(f"  ⚠  Shortfall   : US${shortfall:>9,.2f} ({shortfall/sgx_required_usd*100:.1f}%)")
                print(f"  ℹ  Proceeding on margin — top up USD when possible")
                notify("RodPicks SGX — Margin Used ⚠",
                       f"USD shortfall for SGX: US${shortfall:,.2f}\n"
                       f"(Need US${sgx_required_usd:,.0f} to cover S${SGX_CAPITAL:,.0f} SGX allocation)\n"
                       f"Moomoo will auto-convert USD→SGD. FX spread ~0.2% applies.\n"
                       f"Please top up when funds are available.")

            alloc = SGX_CAPITAL / len(sgx_picks)
            print(f"\n  Order Plan (33.3% per stock):")
            for ticker, d in sgx_picks.items():
                code   = sgx_futu(ticker)
                price  = d["price"]
                shares = calc_lots(alloc, price)
                value  = shares * price
                comm   = value * SGX_COMMISSION
                idle   = alloc - value
                print(f"    BUY {ticker.replace('.SI',''):<6} {shares:>6} shares @ S${price:.3f}"
                      f" = S${value:,.2f}  comm:S${comm:.2f}  idle:S${idle:.2f}")

                if not dry_run and acc_sg:
                    ok, oid = place(t_sg, acc_sg, code, __import__("futu").TrdSide.BUY, price, shares, "SG")
                    if ok:
                        print(f"    ✅ Order placed — ID: {oid}")
                        trades.append({"market":"SGX","ticker":ticker.replace(".SI",""),
                                       "code":code,"shares":shares,"buy_price":price,
                                       "buy_date":today.isoformat(),"order_id":str(oid),
                                       "comm_buy":round(comm,2),"next_rebalance":close_dt.isoformat()})
                    else:
                        print(f"    ❌ Failed: {oid}")
            q_sg.close(); t_sg.close()
        except Exception as e:
            print(f"  SGX connection error: {e}")

    # ── US ────────────────────────────────────────────────────────────────────
    if market in ("US", "BOTH"):
        print(f"\n{'─'*62}")
        print(f"  US — Balance Check (US${US_CAPITAL:,.0f} USD)")
        print(f"{'─'*62}")
        try:
            q_us, t_us = get_moomoo("US")
            acc_us     = get_acc(t_us)
            cash_usd   = get_cash(t_us, acc_us) if acc_us else 0
            shortfall  = max(0, US_CAPITAL - cash_usd)

            print(f"  USD balance  : US${cash_usd:>9,.2f}")
            print(f"  Required     : US${US_CAPITAL:>9,.2f}")
            if shortfall == 0:
                print(f"  ✅ Sufficient USD — no margin needed")
            else:
                print(f"  ⚠  Shortfall   : US${shortfall:>9,.2f} ({shortfall/US_CAPITAL*100:.1f}%)")
                print(f"  ℹ  Proceeding on margin — top up when funds available")
                notify("RodPicks US — Margin Used ⚠",
                       f"USD shortfall: US${shortfall:,.2f} ({shortfall/US_CAPITAL*100:.1f}%)\n"
                       f"Trades will execute on margin.\n"
                       f"Please top up when funds are available.")

            alloc = US_CAPITAL / len(us_picks)
            print(f"\n  Order Plan (20% per stock):")
            for ticker, d in us_picks.items():
                code   = us_futu(ticker)
                price  = d["price"]
                shares = calc_shares(alloc, price)
                value  = shares * price
                comm   = value * US_COMMISSION
                print(f"    BUY {ticker:<6} {shares:>5} shares @ US${price:.2f}"
                      f" = US${value:,.2f}  comm:US${comm:.2f}")

                if not dry_run and acc_us:
                    ok, oid = place(t_us, acc_us, code, __import__("futu").TrdSide.BUY, price, shares, "US")
                    if ok:
                        print(f"    ✅ Order placed — ID: {oid}")
                        trades.append({"market":"US","ticker":ticker,
                                       "code":code,"shares":shares,"buy_price":price,
                                       "buy_date":today.isoformat(),"order_id":str(oid),
                                       "comm_buy":round(comm,2),"next_rebalance":close_dt.isoformat()})
                    else:
                        print(f"    ❌ Failed: {oid}")
            q_us.close(); t_us.close()
        except Exception as e:
            print(f"  US connection error: {e}")

    print(f"\n{'='*62}")
    if not dry_run and trades:
        log = load_log()
        log["open"].extend(trades)
        save_log(log)
        sgx_c = sum(1 for t in trades if t["market"]=="SGX")
        us_c  = sum(1 for t in trades if t["market"]=="US")
        print(f"  ✅ {len(trades)} positions opened — SGX:{sgx_c} | US:{us_c}")
        print(f"  Next rebalance: {close_dt}")
        notify("RodPicks Positions Opened ✅",
               f"SGX: {sgx_c} stocks  |  US: {us_c} stocks\n"
               f"Next rebalance: {close_dt}")
    elif dry_run:
        print(f"  DRY RUN complete — no orders placed.")
        print(f"  Next rebalance: {close_dt}")
    print(f"{'='*62}\n")


# ── Close positions ───────────────────────────────────────────────────────────

def close_positions(dry_run=False, market="BOTH"):
    today   = date.today()
    now_str = datetime.now(SGT).strftime("%Y-%m-%d %H:%M:%S SGT")
    mode    = "DRY RUN" if dry_run else "PAPER TRADE"
    log     = load_log()
    trades  = log.get("open", [])

    print(f"\n{'='*62}")
    print(f"  RodPicks AutoTrader — CLOSE [{mode}] [{market}]")
    print(f"  {now_str}")
    print(f"{'='*62}\n")

    # Filter to requested market
    if market != "BOTH":
        trades = [t for t in trades if t["market"] == market]

    if not trades:
        print("  No open positions found.")
        return

    results = []

    mkt_pairs = [("SGX","SG"), ("US","US")]
    if market == "SGX": mkt_pairs = [("SGX","SG")]
    if market == "US":  mkt_pairs = [("US","US")]

    for market_name, mkts in mkt_pairs:
        mkt_trades = [t for t in trades if t["market"]==market_name]
        if not mkt_trades: continue

        print(f"{'─'*62}")
        print(f"  {market_name} — Closing {len(mkt_trades)} positions")
        print(f"{'─'*62}")

        try:
            q, t = get_moomoo(mkts)
            acc  = get_acc(t)
            cur  = "S$" if market_name=="SGX" else "US$"

            for trade in mkt_trades:
                price     = get_price_live(q, trade["code"]) or trade["buy_price"]
                shares    = trade["shares"]
                comm_sell = shares * price * (SGX_COMMISSION if market_name=="SGX" else US_COMMISSION)
                gross     = (price - trade["buy_price"]) * shares
                net       = gross - trade["comm_buy"] - comm_sell
                ret_pct   = net / (trade["buy_price"] * shares) * 100
                sign      = "+" if net >= 0 else ""

                print(f"\n  {trade['ticker']}")
                print(f"    Bought : {cur}{trade['buy_price']:.3f}  on {trade['buy_date']}")
                print(f"    Selling: {cur}{price:.3f}  today ({today})")
                print(f"    Gross P&L        : {cur}{sign}{gross:,.2f}")
                print(f"    Buy commission   : -{cur}{trade['comm_buy']:.2f}")
                print(f"    Sell commission  : -{cur}{comm_sell:.2f}")
                print(f"    Net P&L          : {cur}{sign}{net:,.2f}  ({sign}{ret_pct:.2f}%)")

                if not dry_run and acc:
                    ok, oid = place(t, acc, trade["code"],
                                    __import__("futu").TrdSide.SELL, price, shares, mkts)
                    print(f"    {'✅ Sold — ID: '+str(oid) if ok else '❌ Failed: '+str(oid)}")

                results.append({
                    "market":market_name,"ticker":trade["ticker"],
                    "shares":shares,"buy_price":trade["buy_price"],
                    "sell_price":price,"buy_date":trade["buy_date"],
                    "sell_date":today.isoformat(),"gross_pnl":round(gross,2),
                    "comm_buy":round(trade["comm_buy"],2),
                    "comm_sell":round(comm_sell,2),"net_pnl":round(net,2),
                    "net_return_pct":round(ret_pct,2),
                })
            q.close(); t.close()
        except Exception as e:
            print(f"  Connection error: {e}")

    if not results: return

    sgx_net   = sum(r["net_pnl"] for r in results if r["market"]=="SGX")
    us_net    = sum(r["net_pnl"] for r in results if r["market"]=="US")
    us_net_sg = us_net / SGD_USD_RATE
    combined  = sgx_net + us_net_sg
    total_comm= sum(r["comm_buy"]+r["comm_sell"] for r in results)

    print(f"\n{'='*62}")
    print(f"  MONTHLY P&L SUMMARY")
    print(f"{'='*62}")
    print(f"  SGX net P&L  : S${sgx_net:>+10,.2f}")
    print(f"  US net P&L   : US${us_net:>+9,.2f}  (≈ S${us_net_sg:>+,.2f})")
    print(f"  Total comms  : S${total_comm:>10,.2f}")
    print(f"  Combined     : S${combined:>+10,.2f}")
    print(f"{'='*62}\n")

    if not dry_run:
        generate_report(results, today)
        # Remove only the closed market's positions from open log
        full_log = load_log()
        closed_tickers = {r["ticker"] for r in results}
        full_log["open"] = [t for t in full_log["open"]
                            if t["ticker"] not in closed_tickers]
        full_log["history"].append({
            "month": today.isoformat()[:7],
            "results": results,
            "sgx_net": round(sgx_net,2),
            "us_net_usd": round(us_net,2),
            "us_net_sgd": round(us_net_sg,2),
            "combined_sgd": round(combined,2),
        })
        save_log(full_log)
        notify("RodPicks Monthly Close ✅",
               f"SGX: S${sgx_net:+,.2f}\n"
               f"US:  US${us_net:+,.2f} (≈S${us_net_sg:+,.2f})\n"
               f"Combined: S${combined:+,.2f}\n"
               f"Report: report_{today}.html")


# ── Rebalance (close existing then open new — monthly 1st) ───────────────────

def rebalance_positions(dry_run=False, market="BOTH"):
    """Sell existing positions then immediately buy new picks. First month: just buys."""
    log = load_log()
    existing = [t for t in log.get("open", [])
                if market == "BOTH" or t["market"] == market]

    if existing:
        print(f"\n  ── Phase 1: Closing existing {market} positions ──")
        close_positions(dry_run=dry_run, market=market)
        print(f"\n  ── Phase 2: Opening new {market} positions ──")
    else:
        print(f"\n  No existing {market} positions — opening fresh.")

    open_positions(dry_run=dry_run, market=market)


# ── HTML Report ───────────────────────────────────────────────────────────────

def generate_report(results, close_date):
    sgx_r    = [r for r in results if r["market"]=="SGX"]
    us_r     = [r for r in results if r["market"]=="US"]
    sgx_net  = sum(r["net_pnl"] for r in sgx_r)
    us_net   = sum(r["net_pnl"] for r in us_r)
    combined = sgx_net + us_net / SGD_USD_RATE

    def rows(rlist, cur):
        out = ""
        for r in rlist:
            c = "#4ade80" if r["net_pnl"] >= 0 else "#f87171"
            out += f"""<tr>
              <td>{r['ticker']}</td><td>{r['shares']:,}</td>
              <td>{cur}{r['buy_price']:.3f}</td><td>{cur}{r['sell_price']:.3f}</td>
              <td>{cur}{r['gross_pnl']:+,.2f}</td>
              <td>-{cur}{r['comm_buy']+r['comm_sell']:.2f}</td>
              <td style="color:{c};font-weight:500">{cur}{r['net_pnl']:+,.2f}</td>
              <td style="color:{c}">{r['net_return_pct']:+.2f}%</td>
            </tr>"""
        return out

    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>RodPicks Report — {close_date}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#0f1117;color:#e2e8f0;padding:24px}}
  h1{{font-size:1.3rem;font-weight:700;margin-bottom:4px}}
  .sub{{color:#64748b;font-size:0.82rem;margin-bottom:20px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
         gap:10px;margin-bottom:24px}}
  .card{{background:#1e293b;border-radius:8px;padding:12px 14px}}
  .l{{font-size:0.65rem;color:#64748b;text-transform:uppercase;margin-bottom:3px}}
  .v{{font-size:1.1rem;font-weight:600}}
  h2{{font-size:0.9rem;font-weight:600;margin:20px 0 10px;color:#94a3b8}}
  table{{width:100%;border-collapse:collapse;font-size:0.8rem;margin-bottom:24px}}
  th{{background:#1e293b;color:#64748b;text-align:left;padding:8px 10px;
      font-size:0.65rem;text-transform:uppercase}}
  td{{padding:8px 10px;border-bottom:1px solid #1e293b;color:#cbd5e1}}
  .note{{color:#475569;font-size:0.7rem;margin-top:8px}}
</style></head><body>
<h1>RodPicks Monthly P&L Report</h1>
<p class="sub">Period close: {close_date} &nbsp;·&nbsp; SGX top 3 (S$30k) + US top 5 (US$50k) &nbsp;·&nbsp; Paper trading</p>
<div class="grid">
  <div class="card"><div class="l">SGX net</div>
    <div class="v" style="color:{'#4ade80' if sgx_net>=0 else '#f87171'}">S${sgx_net:+,.2f}</div></div>
  <div class="card"><div class="l">US net (USD)</div>
    <div class="v" style="color:{'#4ade80' if us_net>=0 else '#f87171'}">US${us_net:+,.2f}</div></div>
  <div class="card"><div class="l">Combined (SGD)</div>
    <div class="v" style="color:{'#4ade80' if combined>=0 else '#f87171'}">S${combined:+,.2f}</div></div>
  <div class="card"><div class="l">Total capital</div>
    <div class="v">S$30k + US$50k</div></div>
</div>
<h2>SGX Positions</h2>
<table><thead><tr><th>Ticker</th><th>Shares</th><th>Buy</th><th>Sell</th>
  <th>Gross P&L</th><th>Commission</th><th>Net P&L</th><th>Return</th></tr></thead>
<tbody>{rows(sgx_r, 'S$')}</tbody></table>
<h2>US Positions</h2>
<table><thead><tr><th>Ticker</th><th>Shares</th><th>Buy</th><th>Sell</th>
  <th>Gross P&L</th><th>Commission</th><th>Net P&L</th><th>Return</th></tr></thead>
<tbody>{rows(us_r, 'US$')}</tbody></table>
<p class="note">SGX: 0.2%/side | US: 0.1%/side | Rate: 1 SGD = {SGD_USD_RATE} USD | Not financial advice.</p>
</body></html>"""

    with open(f"report_{close_date}.html","w",encoding="utf-8") as f:
        f.write(html)


# ── Status ────────────────────────────────────────────────────────────────────

def show_status():
    log    = load_log()
    trades = log.get("open", [])
    if not trades:
        print("\n  No open positions.\n")
        return
    print(f"\n{'='*62}")
    print(f"  Current Holdings — {date.today()}")
    print(f"{'='*62}")
    for market, mkts in [("SGX","SG"),("US","US")]:
        mt = [t for t in trades if t["market"]==market]
        if not mt: continue
        print(f"\n  {market}:")
        try:
            q, t = get_moomoo(mkts)
            cur  = "S$" if market=="SGX" else "US$"
            for trade in mt:
                price = get_price_live(q, trade["code"]) or trade["buy_price"]
                pnl   = (price - trade["buy_price"]) * trade["shares"]
                pct   = (price / trade["buy_price"] - 1) * 100
                sign  = "+" if pnl >= 0 else ""
                print(f"    {trade['ticker']:<8} {trade['shares']:>6} shares | "
                      f"Cost:{cur}{trade['buy_price']:.3f} | "
                      f"Now:{cur}{price:.3f} | "
                      f"P&L:{cur}{sign}{pnl:,.2f} ({sign}{pct:.1f}%) | "
                      f"Close:{trade['close_date']}")
            q.close(); t.close()
        except Exception as e:
            print(f"    Connection error: {e}")
    print()


# ── Backtest (1st of month cycle) ────────────────────────────────────────────

def run_backtest(start_str: str, end_str: str, capital_sgx=30_000, capital_us=50_000):
    """
    Backtest for a specific 15th→14th period.
    Uses actual historical prices for momentum (genuinely historical).
    Uses current fundamentals (minor look-ahead, 20% weight only).
    """
    start = date.fromisoformat(start_str)
    end   = date.fromisoformat(end_str)

    print(f"\n{'='*62}")
    print(f"  RodPicks AutoTrader Backtest")
    print(f"  Open: {start}  →  Close: {end}")
    print(f"  SGX: S${capital_sgx:,}  |  US: US${capital_us:,}")
    print(f"{'='*62}\n")

    buf = (start - timedelta(days=200)).isoformat()

    print("Downloading historical prices...")
    all_tickers = SGX_TICKERS + US_TICKERS + ["ES3.SI", "SPY"]
    raw = yf.download(all_tickers, start=buf, end=(end+timedelta(days=1)).isoformat(),
                      auto_adjust=True, progress=False)["Close"]
    if isinstance(raw, pd.Series): raw = raw.to_frame()
    raw.index = pd.to_datetime(raw.index)

    def price_at(ticker, d):
        if ticker not in raw.columns: return None
        col = raw[ticker].dropna()
        col = col[col.index <= pd.Timestamp(d)]
        return float(col.iloc[-1]) if not col.empty else None

    print("Fetching fundamentals (current — minor look-ahead)...")
    sgx_fund = {t: fetch_fundamentals(t) for t in SGX_TICKERS}
    us_fund  = {t: fetch_fundamentals(t) for t in US_TICKERS}

    # Score at open date
    hist_prices = raw[raw.index <= pd.Timestamp(start)]
    sgx_picks   = score_stocks(SGX_TICKERS, hist_prices, sgx_fund, 3)
    us_picks    = score_stocks(US_TICKERS,  hist_prices, us_fund,  5)

    print(f"\n  Picks on {start} (open date):")
    print(f"  SGX top 3: {', '.join(t.replace('.SI','') for t in sgx_picks)}")
    print(f"  US  top 5: {', '.join(us_picks)}")

    # SGX performance
    print(f"\n{'─'*62}")
    print(f"  SGX RESULTS (S${capital_sgx:,})")
    print(f"{'─'*62}")

    alloc_sgx = capital_sgx / len(sgx_picks)
    sgx_results = []
    for ticker, d in sgx_picks.items():
        buy_p  = price_at(ticker, start)
        sell_p = price_at(ticker, end)
        if not buy_p or not sell_p: continue
        shares    = calc_lots(alloc_sgx, buy_p)
        value_in  = shares * buy_p
        value_out = shares * sell_p
        comm_buy  = value_in  * SGX_COMMISSION
        comm_sell = value_out * SGX_COMMISSION
        gross     = value_out - value_in
        net       = gross - comm_buy - comm_sell
        ret_pct   = net / value_in * 100
        idle      = alloc_sgx - value_in
        sign      = "+" if net >= 0 else ""
        t_short   = ticker.replace(".SI","")
        print(f"  {t_short:<6} | {shares:>6} shares | "
              f"Buy S${buy_p:.3f} → Sell S${sell_p:.3f} | "
              f"Gross:{sign}S${gross:,.2f} | "
              f"Net:{sign}S${net:,.2f} ({sign}{ret_pct:.2f}%) | "
              f"Idle:S${idle:.2f}")
        sgx_results.append({"ticker":t_short,"shares":shares,
                             "buy":buy_p,"sell":sell_p,"gross":gross,
                             "comm":comm_buy+comm_sell,"net":net,"ret":ret_pct,"idle":idle})

    sgx_net   = sum(r["net"] for r in sgx_results)
    sgx_total_comm = sum(r["comm"] for r in sgx_results)
    sgx_idle  = sum(r["idle"] for r in sgx_results)
    print(f"\n  SGX Total Commission : S${sgx_total_comm:,.2f}")
    print(f"  SGX Total Idle Cash  : S${sgx_idle:,.2f}")
    print(f"  SGX Net P&L          : S${sgx_net:+,.2f}")
    print(f"  SGX Net Return       : {sgx_net/capital_sgx*100:+.2f}%")

    # US performance
    print(f"\n{'─'*62}")
    print(f"  US RESULTS (US${capital_us:,})")
    print(f"{'─'*62}")

    alloc_us = capital_us / len(us_picks)
    us_results = []
    for ticker, d in us_picks.items():
        buy_p  = price_at(ticker, start)
        sell_p = price_at(ticker, end)
        if not buy_p or not sell_p: continue
        shares    = calc_shares(alloc_us, buy_p)
        value_in  = shares * buy_p
        value_out = shares * sell_p
        comm_buy  = value_in  * US_COMMISSION
        comm_sell = value_out * US_COMMISSION
        gross     = value_out - value_in
        net       = gross - comm_buy - comm_sell
        ret_pct   = net / value_in * 100
        sign      = "+" if net >= 0 else ""
        print(f"  {ticker:<6} | {shares:>5} shares | "
              f"Buy US${buy_p:.2f} → Sell US${sell_p:.2f} | "
              f"Gross:{sign}US${gross:,.2f} | "
              f"Net:{sign}US${net:,.2f} ({sign}{ret_pct:.2f}%)")
        us_results.append({"ticker":ticker,"shares":shares,
                            "buy":buy_p,"sell":sell_p,"gross":gross,
                            "comm":comm_buy+comm_sell,"net":net,"ret":ret_pct})

    us_net   = sum(r["net"] for r in us_results)
    us_total_comm = sum(r["comm"] for r in us_results)
    us_net_sgd = us_net / SGD_USD_RATE
    print(f"\n  US Total Commission  : US${us_total_comm:,.2f}")
    print(f"  US Net P&L           : US${us_net:+,.2f}  (≈ S${us_net_sgd:+,.2f})")
    print(f"  US Net Return        : {us_net/capital_us*100:+.2f}%")

    # Benchmark
    bm_sgx_buy  = price_at("ES3.SI", start)
    bm_sgx_sell = price_at("ES3.SI", end)
    bm_us_buy   = price_at("SPY",    start)
    bm_us_sell  = price_at("SPY",    end)
    bm_sgx_ret  = (bm_sgx_sell/bm_sgx_buy - 1)*100 if bm_sgx_buy and bm_sgx_sell else 0
    bm_us_ret   = (bm_us_sell /bm_us_buy  - 1)*100 if bm_us_buy  and bm_us_sell  else 0

    combined     = sgx_net + us_net_sgd
    total_inv_sgd= capital_sgx + capital_us / SGD_USD_RATE

    print(f"\n{'='*62}")
    print(f"  COMBINED SUMMARY  ({start} → {end})")
    print(f"{'='*62}")
    print(f"  SGX net P&L          : S${sgx_net:>+10,.2f}  ({sgx_net/capital_sgx*100:+.2f}%)")
    print(f"  US net P&L           : US${us_net:>+9,.2f}  ({us_net/capital_us*100:+.2f}%)  ≈ S${us_net_sgd:+,.2f}")
    print(f"  Total commission     : S${sgx_total_comm+us_total_comm/SGD_USD_RATE:>+10,.2f}")
    print(f"  Combined net (SGD)   : S${combined:>+10,.2f}")
    print(f"  Overall return       : {combined/total_inv_sgd*100:+.2f}%")
    print(f"\n  Benchmark comparison:")
    print(f"  STI ETF (ES3)        : {bm_sgx_ret:+.2f}%")
    print(f"  S&P 500 (SPY)        : {bm_us_ret:+.2f}%")
    print(f"\n  Alpha vs STI         : {sgx_net/capital_sgx*100 - bm_sgx_ret:+.2f}pp")
    print(f"  Alpha vs S&P 500     : {us_net/capital_us*100 - bm_us_ret:+.2f}pp")
    print(f"{'='*62}\n")

    # Save report
    fname = f"backtest_{start}_{end}.json"
    with open(fname,"w") as f:
        json.dump({"start":str(start),"end":str(end),
                   "sgx_capital":capital_sgx,"us_capital":capital_us,
                   "sgx_picks":list(sgx_picks.keys()),
                   "us_picks":list(us_picks.keys()),
                   "sgx_net":round(sgx_net,2),"us_net_usd":round(us_net,2),
                   "us_net_sgd":round(us_net_sgd,2),"combined_sgd":round(combined,2),
                   "sgx_results":sgx_results,"us_results":us_results},f,indent=2)
    print(f"✅ Backtest saved → {fname}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="RodPicks AutoTrader")
    p.add_argument("--rebalance", action="store_true", help="Close existing + open new picks (monthly 1st)")
    p.add_argument("--market",    type=str, default="BOTH", choices=["SGX","US","BOTH"],
                   help="Which market to act on (default: BOTH)")
    p.add_argument("--status",    action="store_true", help="Show current holdings")
    p.add_argument("--dry",       action="store_true", help="Preview only, no orders placed")
    p.add_argument("--backtest",  action="store_true", help="Run backtest")
    p.add_argument("--start",     type=str, default="2026-01-01", help="Backtest open date")
    p.add_argument("--end",       type=str, default="2026-01-31", help="Backtest close date")
    args = p.parse_args()

    if args.backtest:
        run_backtest(args.start, args.end)
    elif args.rebalance:
        rebalance_positions(dry_run=args.dry, market=args.market)
    elif args.status:
        show_status()
    else:
        p.print_help()
