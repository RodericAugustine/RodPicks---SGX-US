"""
RodPicks AutoTrader — Monthly Rebalance Reminder Email
====================================================
Sends an email the day before the 1st to remind you to:
  1. Launch Moomoo OpenD (desktop app)
  2. Log in to your paper/live account
  3. Ensure your computer stays on overnight (US trade runs at 9:35pm SGT)

Setup (one-time):
  1. Go to https://myaccount.google.com/apppasswords
  2. Create an App Password for "RodPicks AutoTrader"
  3. Paste it into GMAIL_APP_PASSWORD below (or set env var RodPicks_EMAIL_PASS)

Run: python send_reminder.py
"""

import os
import smtplib
import sys
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── Config (set both env vars before running) ──────────────────────────────────
GMAIL_ADDRESS      = os.environ.get("RODPICKS_EMAIL", "")        # your Gmail address
GMAIL_APP_PASSWORD = os.environ.get("RodPicks_EMAIL_PASS", "")   # Gmail App Password
TO_ADDRESS         = os.environ.get("RODPICKS_EMAIL", "")        # recipient (same address)

if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
    print("❌ Missing env vars. Set both before running:")
    print("   [System.Environment]::SetEnvironmentVariable('RODPICKS_EMAIL','you@gmail.com','User')")
    print("   [System.Environment]::SetEnvironmentVariable('RodPicks_EMAIL_PASS','your-app-password','User')")
    sys.exit(1)
# ──────────────────────────────────────────────────────────────────────────────

def tomorrow_is_first() -> bool:
    """Returns True only if tomorrow is the 1st of the month."""
    return (date.today() + timedelta(days=1)).day == 1


def get_next_rebalance_date() -> date:
    """Returns the 1st of next month."""
    today = date.today()
    if today.month == 12:
        return date(today.year + 1, 1, 1)
    return date(today.year, today.month + 1, 1)


def send_reminder():
    rebalance_date = get_next_rebalance_date()
    day_str = rebalance_date.strftime("%d %b %Y")

    subject = f"⏰ RodPicks AutoTrader: Rebalance Tomorrow ({day_str})"

    body_html = f"""
    <html><body style="font-family: Arial, sans-serif; font-size: 14px; color: #333;">
    <h2 style="color: #1a6fbf;">RodPicks AutoTrader — Monthly Rebalance Tomorrow</h2>
    <p>Your automated trading system will rebalance on <strong>{day_str}</strong>.</p>

    <h3>✅ Checklist for tonight / tomorrow morning:</h3>
    <ol>
      <li><strong>Launch Moomoo OpenD</strong> — open the Moomoo desktop app and make sure OpenD is running (check system tray)</li>
      <li><strong>Log in to your account</strong> — ensure you're logged into your paper or live trading account</li>
      <li><strong>Keep your computer ON</strong> — the US rebalance runs at <strong>9:35 PM SGT</strong>, so don't shut down before then</li>
      <li><strong>Check internet connection</strong> — a stable connection is needed for order execution</li>
      <li><strong>Confirm capital balances</strong>:
        <ul>
          <li>SGX account: sufficient balance available</li>
          <li>US account: sufficient balance available</li>
        </ul>
      </li>
    </ol>

    <h3>📅 Tomorrow's Schedule:</h3>
    <table style="border-collapse: collapse; width: 100%;">
      <tr style="background: #f0f4ff;">
        <th style="padding: 8px; border: 1px solid #ccc; text-align: left;">Time (SGT)</th>
        <th style="padding: 8px; border: 1px solid #ccc; text-align: left;">Task</th>
      </tr>
      <tr>
        <td style="padding: 8px; border: 1px solid #ccc;">8:00 AM</td>
        <td style="padding: 8px; border: 1px solid #ccc;">Signal preview — dry run of both SGX &amp; US picks</td>
      </tr>
      <tr style="background: #f9f9f9;">
        <td style="padding: 8px; border: 1px solid #ccc;">9:05 AM</td>
        <td style="padding: 8px; border: 1px solid #ccc;">SGX rebalance — sell existing + buy top 3 picks (configured capital)</td>
      </tr>
      <tr>
        <td style="padding: 8px; border: 1px solid #ccc;">9:35 PM</td>
        <td style="padding: 8px; border: 1px solid #ccc;">US rebalance — sell existing + buy top 5 picks (configured capital)</td>
      </tr>
    </table>

    <p style="margin-top: 20px; color: #888; font-size: 12px;">
      This reminder was sent automatically by RodPicks AutoTrader.<br>
      To check today's signal picks: <code>python rodpicks_autotrader.py --rebalance --dry</code>
    </p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = TO_ADDRESS
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, TO_ADDRESS, msg.as_string())
        print(f"✅ Reminder sent to {TO_ADDRESS} — rebalance date: {day_str}")
    except smtplib.SMTPAuthenticationError:
        print("❌ Authentication failed. Check your Gmai