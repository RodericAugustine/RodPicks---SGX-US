# RodPicks AutoTrader

Automated monthly rebalancing system for SGX and US stocks using a factor-based scoring model. Connects to Moomoo via futu-api and runs on Windows Task Scheduler.

## Strategy

Scores stocks monthly using:
- **Momentum 1m/3m/6m** — 80% weight
- **ROE** — 10% weight
- **Free Cash Flow** — 10% weight

Buys the top 3 SGX picks (S$<YOUR_CAPITAL>) and top 5 US picks (US$<YOUR_CAPITAL>) on the 1st of each month. Fully replaces the portfolio each month.

## Schedule

| Time (SGT) | Task |
|------------|------|
| Last day, 9:00am | Email reminder to prep OpenD |
| 1st, 8:00am | Dry run signal preview |
| 1st, 9:05am | SGX rebalance |
| 1st, 9:35pm | US rebalance |

## Files

| File | Purpose |
|------|---------|
| `rodpicks_autotrader.py` | Main script — scoring, execution, backtest |
| `rodpicks_sg.py` | SGX signal generator |
| `rodpicks_us.py` | US signal generator |
| `send_reminder.py` | Monthly email reminder |
| `setup_autotrader.ps1` | Registers Windows Task Scheduler tasks |
| `backtest_3m.py` | Dec 2025 – Feb 2026 backtest |
| `backtest_jun25.py` | Jun 2025 – Aug 2025 backtest |
| `test_connection.py` | Tests Moomoo OpenD connection |
| `test_email.py` | Tests Gmail reminder email |

## Setup

### Requirements
```
pip install futu-api yfinance pandas numpy
```

### 1. Configure Moomoo OpenD
- Install and launch the Moomoo desktop app
- Ensure OpenD is running (system tray)
- Test connection: `python test_connection.py`

### 2. Configure Gmail reminder
- Create an App Password at https://myaccount.google.com/apppasswords
- Set environment variable:
```powershell
[System.Environment]::SetEnvironmentVariable('RodPicks_EMAIL_PASS','your-app-password','User')
```
- Test: `python test_email.py`

### 3. Register scheduled tasks
Run as Administrator:
```powershell
.\setup_autotrader.ps1
```

### 4. Test signal
```
python rodpicks_autotrader.py --rebalance --dry
```

## Capital

| Market | Capital | Picks | Per Stock |
|--------|---------|-------|-----------|
| SGX | S$<YOUR_CAPITAL> | Top 3 | ~equal split |
| US | US$<YOUR_CAPITAL> | Top 5 | ~equal split |

SGX trades fund via USD auto-conversion. Ensure sufficient USD balance before the 1st.

## Notes
- Paper trading: change `TrdEnv.REAL` to `TrdEnv.SIMULATE` in `rodpicks_autotrader.py`
- SGX lot size: floored to nearest 100 shares
- Margin account bridges T+1/T+2 settlement gap on rebalance day
