import os, smtplib
from email.mime.text import MIMEText

addr = os.environ.get("RODPICKS_EMAIL", "")
pw   = os.environ.get("RodPicks_EMAIL_PASS", "")

if not addr or not pw:
    print("❌ Missing env vars. Set both before running:")
    print("   [System.Environment]::SetEnvironmentVariable('RODPICKS_EMAIL','you@gmail.com','User')")
    print("   [System.Environment]::SetEnvironmentVariable('RodPicks_EMAIL_PASS','your-app-password','User')")
else:
    try:
        msg = MIMEText("Test from RodPicks AutoTrader — email reminder is working!")
        msg["Subject"] = "RodPicks Connection Test ✅"
        msg["From"]    = addr
        msg["To"]      = addr
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(addr, pw)
            s.sendmail(addr, addr, msg.as_string())
        print(f"✅ Email sent — check your inbox")
    except smtplib.SMTPAuthenticationError:
        print("❌ Authentication failed — App Password is wrong or not set up.")
        print("   Go to: https://myaccount.google.com/apppasswords")
    except Excep