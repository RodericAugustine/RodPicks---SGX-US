"""
RodPicks AutoTrader — Moomoo OpenD Connection Test
===============================================
Run this to verify your OpenD desktop app is running and reachable.
Shows connected accounts, balances, and current positions.

Requirements:
  1. Moomoo desktop app must be open
  2. OpenD must be running (check system tray)
  3. You must be logged in

Run: python test_connection.py
"""

import sys
from futu import (
    OpenQuoteContext, OpenSecTradeContext,
    TrdMarket, TrdEnv, SecurityFirm, RET_OK
)

# All known SecurityFirm values to probe
FIRMS = {
    "FUTUINC (Moomoo US)":       SecurityFirm.FUTUINC,
    "FUTUSECURITIES (Futu HK)":  SecurityFirm.FUTUSECURITIES,
}
# Add FUTUSG if this version of futu-api has it
if hasattr(SecurityFirm, "FUTUSG"):
    FIRMS["FUTUSG (Moomoo SG)"] = SecurityFirm.FUTUSG
if hasattr(SecurityFirm, "MOOMOOFINANCIALSG"):
    FIRMS["MOOMOOFINANCIALSG"] = SecurityFirm.MOOMOOFINANCIALSG

OPEND_HOST   = "127.0.0.1"
OPEND_PORT   = 11111
TRADE_ENV    = TrdEnv.REAL         # Live trading account

SEP  = "=" * 65
SEP2 = "─" * 65

print(f"\n{SEP}")
print("  RodPicks — Moomoo OpenD Connection Test")
print(SEP)

# ── 1. Quote context (market data) ───────────────────────────────────────────
print("\n[1] Connecting to OpenD (market data)...")
quote_ctx = None
try:
    quote_ctx = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
    ret, data = quote_ctx.get_global_state()
    if ret == RET_OK:
        print(f"  ✅ Connected to OpenD")
        # data may be a dict or DataFrame depending on API version
        if hasattr(data, 'columns'):
            for col in data.columns:
                print(f"     {col:<20}: {data[col].values[0]}")
        elif isinstance(data, dict):
            for k, v in data.items():
                print(f"     {k:<20}: {v}")
        else:
            print(f"     Info: {data}")
    else:
        print(f"  ⚠  get_global_state returned: {data}")
    quote_ctx.close()
    quote_ctx = None
except Exception as e:
    print(f"  ⚠  Global state error (non-fatal): {e}")
    if quote_ctx:
        try: quote_ctx.close()
        except: pass
    print("  Continuing to trade account tests...\n")

# ── 2 & 3. Probe all security firm × market combinations ─────────────────────
mode_label = "LIVE" if TRADE_ENV == TrdEnv.REAL else "PAPER"
print(f"\n[2] Probing all SecurityFirm × Market combinations ({mode_label})...")
print(f"    Available firms to test: {list(FIRMS.keys())}\n")

found_sg_firm = None
found_us_firm = None

for firm_name, firm_val in FIRMS.items():
    for mkt_label, mkt_val in [("SG", TrdMarket.SG), ("US", TrdMarket.US)]:
        try:
            ctx = OpenSecTradeContext(
                filter_trdmarket=mkt_val,
                host=OPEND_HOST, port=OPEND_PORT,
                security_firm=firm_val
            )
            ret, data = ctx.accinfo_query(trd_env=TRADE_ENV, acc_id=0)
            if ret == RET_OK and not data.empty:
                row = data.iloc[0]
                print(f"  ✅ {mkt_label} market | {firm_name}")
                # Print ALL fields returned so we can see currency, sub-accounts, etc.
                for col in data.columns:
                    val = row.get(col, 'N/A')
                    if val not in (None, '', 'N/A', 0.0) or col in ('acc_id','cash','currency'):
                        print(f"     {col:<25}: {val}")

                # Show positions
                ret2, pos = ctx.position_list_query(trd_env=TRADE_ENV, acc_id=0)
                if ret2 == RET_OK and not pos.empty:
                    print(f"     Positions ({len(pos)}):")
                    for _, r in pos.iterrows():
                        pnl = r.get('pl_val', 0)
                        print(f"       {str(r.get('code','')):<12} {str(r.get('stock_name',''))[:20]:<20} "
                              f"qty={r.get('qty',0):,.0f}  P&L={pnl:+,.2f}")
                else:
                    print(f"     Positions   : None")

                if mkt_label == "SG": found_sg_firm = firm_name
                if mkt_label == "US": found_us_firm = firm_name
            else:
                print(f"  ✗  {mkt_label} market | {firm_name}: {str(data)[:80]}")
            ctx.close()
            print()
        except Exception as e:
            print(f"  ✗  {mkt_label} market | {firm_name}: {e}")
            print()

print(SEP2)
if found_sg_firm:
    print(f"  ✅ Use SecurityFirm.{found_sg_firm.split('(')[0].strip().replace(' ','')} for SG trades")
else:
    print(f"  ❌ No working SG firm found — check Moomoo account type")
if found_us_firm:
    print(f"  ✅ Use SecurityFirm.{found_us_firm.split('(')[0].strip().replace(' ','')} for US trades")
else:
    print(f"  ❌ No working US firm found — check Moomoo account type")

print(f"\n{SEP}")
print("  Connection test complete.")
print(f"  Trading mode: {'🔴 LIVE — real money!' if TRADE_ENV == TrdEnv.REAL else '⚠  PAPER (SIMULATE)'}")
print(f"  To switch modes, change TRADE_ENV at the top of this file.")
print(SEP)
print()
