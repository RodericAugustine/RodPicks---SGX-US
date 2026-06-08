# RodPicks AutoTrader — System Summary

---

## Overview

A fully automated monthly rebalancing system that trades SGX (Singapore) and US stocks using a factor-based scoring model. Runs via Windows Task Scheduler, connects to Moomoo via futu-api, and manages two separate capital pools.

---

## Capital Allocation

| Market | Capital | Picks | Per Stock |
|--------|---------|-------|-----------|
| SGX    | S$<YOUR_CAPITAL> | Top 3 | ~equal split |
| US     | US$<YOUR_CAPITAL> | Top 5 | ~equal split |

---

## Monthly Cycle (runs on the 1st of every month)

### Step 1 — Signal Preview (8:00am SGT)
`python rodpicks_autotrader.py --rebalance --dry`

Dry run: scores and ranks stocks for both markets, prints the picks and estimated order sizes. No orders placed. Gives you visibility before live execution.

### Step 2 — SGX Rebalance (9:05am SGT)
`python rodpicks_autotrader.py --rebalance --market SGX`

- Sells all existing SGX positions
- Immediately buys the new top 3 SGX picks
- SGX lot size: minimum 100 shares per order
- Settlement: T+2, but margin account bridges the gap so sell proceeds fund the buys same day

### Step 3 — US Rebalance (9:35pm SGT = 9:35am EST)
`python rodpicks_autotrader.py --rebalance --market US`

- Sells all existing US positions
- Immediately buys the new top 5 US picks
- Settlement: T+1, margin account bridges same-day

### Reminder Email (last day of each month, 9:00am SGT)
`python send_reminder.py`

- Script checks if tomorrow is the 1st — if not, exits silently
- If yes, sends an HTML email to YOUR_EMAIL@gmail.com with:
  - Checklist: launch Moomoo OpenD, log in, keep PC on overnight
  - Day's schedule: 8am signal, 9:05am SGX trade, 9:35pm US trade
  - Capital balances to confirm

---

## Margin Trading

The system always executes. If sale proceeds + existing cash don't fully cover the new purchases:
- Moomoo's margin account covers the shortfall automatically
- A Windows popup notification is triggered to alert you
- If SGD is short and USD needs to be converted: Moomoo auto-converts with no explicit fee, but a floating FX spread (~0.2%) is embedded in the exchange rate

---

## Files

| File | Purpose |
|------|---------|
| `rodpicks_autotrader.py` | Main script — scoring, order execution, backtest |
| `rodpickssg_v2.py` | SGX signal generator → `dashboard_SG.html` |
| `rodpicksus_v1.py` | US signal generator → `dashboard_us.html` |
| `send_reminder.py` | Monthly email reminder |
| `setup_autotrader.ps1` | Registers all 4 tasks in Windows Task Scheduler (run as Admin) |
| `backtest_3m.py` | Standalone 3-month backtest script |
| `dashboard_SG.html` | SGX top 3 picks dashboard |
| `dashboard_us.html` | US top 5 picks dashboard |
| `autotrader_log.json` | Live trade log (open/closed positions) |

---

## Scheduled Tasks (Task Scheduler → \RodPicks\)

| Task | Day | Time (SGT) | Action |
|------|-----|------------|--------|
| RodPicks-Reminder | 28th* | 9:00am | Email reminder (only sends if tomorrow = 1st) |
| RodPicks-Signal | 1st | 8:00am | Dry run preview |
| RodPicks-SGX-Trade | 1st | 9:05am | Rebalance SGX |
| RodPicks-US-Trade | 1st | 9:35pm | Rebalance US |

*Fires on 28th but script self-checks — email only goes out on the actual last day of the month.

---

## Investment Strategy Logic

### Universe
- **SGX**: Blue-chip and mid-cap SGX-listed stocks (manually defined ticker list)
- **US**: S&P 500 or defined large-cap US stocks

### Scoring Model (per stock, each month)

Each stock gets a composite score out of 100:

| Factor | Weight | What it measures |
|--------|--------|-----------------|
| Momentum — 1 month | 30% | Recent price performance |
| Momentum — 3 month | 25% | Medium-term trend |
| Momentum — 6 month | 25% | Longer-term trend |
| Return on Equity (ROE) | 10% | Profitability / capital efficiency |
| Free Cash Flow (FCF) | 10% | Cash generation quality |

**Total momentum weight = 80%.** The strategy is primarily momentum-driven — it buys stocks that have been going up across multiple timeframes and are also fundamentally sound (profitable + cash generative).

### Why Momentum Dominates (80%)

Momentum is one of the most empirically robust factors in finance. Stocks that have outperformed over 1–6 months tend to continue outperforming in the near term. By layering three timeframes (1m, 3m, 6m), the model favours stocks with consistent upward trends rather than one-off spikes.

### Why ROE + FCF (20%)

Pure momentum can pick up speculative stocks with no earnings. ROE and FCF act as quality filters — they ensure the shortlisted stocks are actually profitable and generating real cash, reducing the risk of holding momentum in low-quality names.

### Selection

- Top 3 SGX scorers → equal-weight allocation of S$<YOUR_CAPITAL> ÷ 3
- Top 5 US scorers → equal-weight allocation of US$<YOUR_CAPITAL> ÷ 5

### Rebalance Logic

Every month the scores are recalculated fresh. The portfolio is fully replaced — there's no partial rebalancing. If a stock scores highly again it gets re-bought; if it drops out of the top picks it gets sold. This keeps the portfolio always holding the current best-scoring names.

### Settlement & Margin Bridge

Since sell proceeds settle T+2 (SGX) and T+1 (US), but the new buys happen the same day, a margin account is used to bridge the gap. In practice, as long as the portfolio hasn't lost significant value, the sale proceeds are sufficient to cover the new purchases and margin is rarely drawn.

---

## Setup Checklist (first time)

1. Install dependencies: `pip install futu-api yfinance pandas numpy`
2. Install and launch **Moomoo OpenD** desktop app
3. Set Gmail App Password for reminder emails:
   - Visit https://myaccount.google.com/apppasswords
   - Create password → copy it
   - Run in PowerShell: `[System.Environment]::SetEnvironmentVariable('RodPicks_EMAIL_PASS','your-password','User')`
4. Run `setup_autotrader.ps1` as Administrator to register all 4 scheduled tasks
5. Test: `python rodpicks_autotrader.py --rebalance --dry`
6. Test: `python send_reminder.py` (only sends email if today is the last day of the month)
